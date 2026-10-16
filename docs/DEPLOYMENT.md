# Going live

This takes about an hour of clicking and pasting, plus waiting for a few approvals. You don't need Docker or the AWS command line on your own computer: everything runs in GitHub Actions, the AWS console, and **AWS CloudShell** (a terminal in your browser, opened from the `>_` icon at the top of the AWS console).

## What you end up with

```
           your-domain.com
                 │
            CloudFront ─────────── /api/* ──► Lambda (FastAPI container) ──► Neon Postgres
                 │                               │        │
        S3 (website files)          S3 (PDFs, signatures)  SES (email)
                                                     ▲
                       EventBridge (nightly upkeep) ─┘

 GitHub Actions: test → migrate → build image → update AWS → upload site → go-live checks
 GitHub Actions (nightly): database dump → S3 backups bucket
```

Monthly cost for one shop: roughly $1–2 of AWS plus your domain, and Stripe's fee per card payment. Details: README → Production Cost Estimate.

## Before you start

| You need | Where | Notes |
|---|---|---|
| AWS account | aws.amazon.com | Turn on MFA for the root user. Use region **us-east-1** (N. Virginia) throughout. |
| Neon account | neon.tech | Free plan. |
| A domain | Any registrar, or Route 53 | Optional for the first deploy; the site works on a CloudFront address until you have one. |
| Stripe account | stripe.com | Optional at first. Business verification can take a few days, so start it early. |
| Admin access to the GitHub repo | github.com/jumpstartcoding/shop | To add secrets and variables. |

Values you'll collect as you go (keep them in a password manager):
- `DATABASE_URL`: the Neon connection string
- `ORIGIN_SECRET`: a random string you generate
- the bootstrap stack outputs (three ARNs/URIs)

---

## 1. Create the database (Neon)

1. In Neon, **New project**. Name `shop`, Postgres version: the newest offered, region **AWS US East 1 (N. Virginia)**, the same region as the app.
2. On the project dashboard, **Connect**. Leave **Connection pooling** off (the app works with either; the direct connection is simplest) and copy the connection string. It looks like:
   `postgresql://neondb_owner:...@ep-xxxx.us-east-1.aws.neon.tech/neondb?sslmode=require`

That's your `DATABASE_URL`.

## 2. Generate the origin secret

In CloudShell (or any terminal):
```bash
openssl rand -hex 32
```
That 64-character value is your `ORIGIN_SECRET`. CloudFront sends it with every API request; the API refuses requests without it.

## 3. Store the app's secrets in AWS

The app reads these from **Systems Manager Parameter Store** each time it starts, so they never sit in code or in the AWS console's function settings. In CloudShell, run this; it asks for the value without showing it:
```bash
read -rsp "Neon connection string: " V && echo && \
aws ssm put-parameter --name /shop/prod/DATABASE_URL --type SecureString --value "$V" --overwrite && unset V
```
Stripe keys get added the same way later (step 10).

## 4. One-time AWS setup (bootstrap stack)

This creates the things GitHub needs to deploy without stored AWS keys (an OIDC trust, two roles), the image repository, and an AWS budget alert. In CloudShell:
```bash
git clone https://github.com/jumpstartcoding/shop.git && cd shop
aws cloudformation deploy --stack-name shop-bootstrap --template-file infra/bootstrap.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides BudgetEmail=you@example.com MonthlyBudgetUsd=10
```
If it fails saying the GitHub identity provider already exists, add `CreateGitHubOidcProvider=false` to the overrides and run it again.

Show the outputs:
```bash
aws cloudformation describe-stacks --stack-name shop-bootstrap \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output table
```
Keep `DeployRoleArn`, `CloudFormationExecutionRoleArn`, and `ImageRepositoryUri` for the next step. AWS emails you to confirm the budget alert subscription.

## 5. Decide on the domain

Pick one. You can start with C and switch later; only GitHub variables change.

**A. DNS in Route 53 (recommended, $0.50/month).** The stack then creates the HTTPS certificate, the site's DNS records, and the email-signing records itself.
- If you're buying a domain, buy it in Route 53 and the hosted zone is created for you.
- If you already own one elsewhere: Route 53 → **Hosted zones → Create hosted zone** for the domain, then at your registrar replace the nameservers with the four Route 53 shows. Copy the **Hosted zone ID**.

Variables to set in step 6: `DOMAIN_NAME`, `HOSTED_ZONE_ID`.

**B. Keep DNS at your registrar.**
- Certificate Manager (in **us-east-1**) → **Request** a public certificate for the exact site name (e.g. `www.yourshop.com`), DNS validation. Add the CNAME it shows at your registrar and wait until it says **Issued**. Copy its ARN.
- After the first deploy, add a CNAME at your registrar from the site name to the stack's `CloudFrontDomain` output, plus the three `EmailDkimRecords` CNAMEs. A bare apex domain (`yourshop.com` without `www`) needs your registrar's ALIAS/ANAME or forwarding feature.

Variables: `DOMAIN_NAME`, `CERTIFICATE_ARN`.

**C. No domain yet.** Leave the domain variables unset. After the first deploy, copy the `SiteUrl` output (`https://dxxxx.cloudfront.net`) and store it:
```bash
aws ssm put-parameter --name /shop/prod/PUBLIC_BASE_URL --type String --value "https://dxxxx.cloudfront.net" --overwrite
```
then restart the API (see "Restarting the API" below). Customer links and payment pages use this address, so set it before sending anything to customers. Delete this parameter once you add a domain.

## 6. Connect GitHub

Repo → **Settings → Secrets and variables → Actions**.

**Secrets** tab:
| Name | Value |
|---|---|
| `DATABASE_URL` | Neon connection string (used for migrations and backups) |
| `ORIGIN_SECRET` | the value from step 2 |

**Variables** tab:
| Name | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | bootstrap output `DeployRoleArn` |
| `AWS_CFN_ROLE_ARN` | bootstrap output `CloudFormationExecutionRoleArn` |
| `AWS_ECR_REPOSITORY` | bootstrap output `ImageRepositoryUri` |
| `AWS_REGION` | `us-east-1` |
| `EMAIL_FROM_ADDRESS` | e.g. `service@yourshop.com` (its domain gets set up in SES; with option A it must be the hosted zone's domain) |
| `ALERT_EMAIL` | where error alerts go |
| `DOMAIN_NAME` | option A or B, e.g. `www.yourshop.com` |
| `HOSTED_ZONE_ID` | option A |
| `CERTIFICATE_ARN` | option B |

Optional: `RESERVED_CONCURRENCY` (leave unset on a new AWS account), `STACK_NAME` (default `shop`).

## 7. Deploy

**Actions → Deploy → Run workflow** (or push to `main`). The first run takes 15–30 minutes, mostly CloudFront and the certificate. It:
1. runs every test, the frontend build, and the Lambda image smoke test;
2. applies database migrations to Neon;
3. builds and pushes the API image;
4. creates or updates the AWS stack;
5. uploads the website;
6. runs the **go-live checks** and puts them on the run's **Summary** page.

Expect ⚠️ on the first run for the owner login, email (SES sandbox), Stripe, and the placeholder shop details. Those are the next steps. ❌ on database, schema, storage, or PDF fails the deploy; see Troubleshooting.

AWS emails `ALERT_EMAIL` an SNS subscription confirmation; click it so alerts reach you.

## 8. Shop profile and owner login

Get the function name:
```bash
FN=$(aws cloudformation describe-stacks --stack-name shop \
  --query "Stacks[0].Outputs[?OutputKey=='ApiFunctionName'].OutputValue" --output text)
```

Load the placeholder shop profile and the standard services list, so the public site isn't empty (skip if you'd rather type everything in Settings):
```bash
aws lambda invoke --function-name "$FN" --cli-binary-format raw-in-base64-out \
  --payload '{"task":"setup_shop"}' /dev/stdout
```

Create your login (12+ character password; it isn't shown or saved in history):
```bash
read -rp "Email: " E; read -rp "Name: " N; read -rsp "Password: " P; echo
jq -n --arg e "$E" --arg n "$N" --arg p "$P" '{task:"create_admin",email:$e,name:$n,password:$p}' > admin.json
aws lambda invoke --function-name "$FN" --cli-binary-format raw-in-base64-out \
  --payload file://admin.json /dev/stdout; rm admin.json; unset P
```
Then sign in at `https://your-site/admin` and fill in **Settings**: real name, address, phone, hours, shop email, tax rate, labor rate, logo, and the authorization, terms, and warranty wording.

## 9. Email (Amazon SES)

The stack registered your email domain with SES.
1. **Verification.** With option A it verifies itself within minutes. Otherwise add the three `EmailDkimRecords` CNAMEs at your registrar. SES console → **Identities** shows *Verified* when done.
2. **Production access.** New SES accounts are in a sandbox: they can only send to addresses you've verified. SES console → **Account dashboard → Request production access**. Describe it plainly: *transactional email for an auto repair shop's own customers: appointment confirmations, estimates, invoices, and receipts they asked for; about 300 a month; no marketing.* AWS usually answers within a day.
3. Until then, verify your own address under **Identities** to test.
4. Recommended: add a DMARC record to the domain's DNS: TXT `_dmarc` → `v=DMARC1; p=none;` (Gmail and Yahoo look for one).

## 10. Online payments (Stripe)

Follow [PAYMENTS.md](PAYMENTS.md) for the Stripe side. The webhook URL is `https://your-site/api/webhooks/stripe`. Store the keys:
```bash
read -rsp "Stripe secret key: " V && echo && aws ssm put-parameter --name /shop/prod/STRIPE_SECRET_KEY --type SecureString --value "$V" --overwrite
read -rsp "Webhook signing secret: " V && echo && aws ssm put-parameter --name /shop/prod/STRIPE_WEBHOOK_SECRET --type SecureString --value "$V" --overwrite; unset V
```
Restart the API, then re-run the Deploy workflow (or run the checks by hand, below). The Online payments check confirms the key works and the webhook is registered with every event the app needs.

## 11. Backups

Turn on the nightly backup: [BACKUPS.md → Turning on nightly backups](BACKUPS.md#turning-on-nightly-backups).

## 12. Final check

- [ ] Go-live checks: all ✅ (⚠️ only for things you've chosen to leave, like Stripe test mode).
- [ ] Book an appointment on the public site from your phone; it shows up on the dashboard.
- [ ] Send yourself an estimate, sign it on your phone, and check the signed PDF.
- [ ] Pay a $1 test invoice online in Stripe test mode, check the receipt email, then refund it.
- [ ] A nightly backup has run.
- [ ] Everything in [SECURITY.md → Owner checklist](SECURITY.md#owner-checklist).

---

## Day to day

**Shipping changes.** Push to `main`. The Deploy workflow tests everything and deploys only if it all passes. A failed deploy leaves the previous version running (CloudFormation rolls back).

**Running the go-live checks by hand:**
```bash
aws lambda invoke --function-name "$FN" --cli-binary-format raw-in-base64-out \
  --payload '{"task":"doctor"}' /dev/stdout | jq -r '.checks[] | "\(.status)\t\(.title): \(.detail)"'
```

**Restarting the API** (after changing a Parameter Store value; the app reads them when it starts):
```bash
aws lambda update-function-configuration --function-name "$FN" --description "restarted $(date -u +%FT%TZ)" >/dev/null
```

**Logs.** CloudWatch → **Log groups** → `/shop/shop/api`. Every request is one JSON line with a `request_id`; errors have `"level": "error"`. Logs are kept 30 days.

**Rotating secrets.**
- Database password: Neon → Roles → reset password, then update `DATABASE_URL` in Parameter Store and in the GitHub secret, then restart the API.
- Stripe: roll the key in the Stripe dashboard, update Parameter Store, restart.
- Origin secret: update the GitHub secret and re-run Deploy (CloudFront and the function get the new value together).

**Rolling back.** Revert the bad commit (`git revert`) and push; the previous image is rebuilt and deployed. The image repository keeps the last 5 images.

**Database migrations** run before new code goes live, while the old code is still serving. Keep them backward compatible: add tables and columns freely; remove or rename only in a later release, once no running code uses the old name.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Deploy job shows **skipped** | `AWS_DEPLOY_ROLE_ARN` isn't set (step 6). |
| "Not authorized to perform sts:AssumeRoleWithWebIdentity" | The run isn't on `main`, or `GitHubRepository` in the bootstrap stack doesn't match the repo name. |
| Stack ends in `ROLLBACK_COMPLETE` on the first deploy | Open the stack's **Events** tab and find the first `CREATE_FAILED` reason, fix it, **delete the `shop` stack**, and re-run. A failed first create can't be updated in place. The files and backups buckets are kept; delete them by hand if they're empty. |
| Stuck on the certificate for 30+ minutes | DNS validation isn't visible yet. With option A, check the registrar uses the Route 53 nameservers (`dig NS yourshop.com`). |
| "Specified ReservedConcurrentExecutions ... decreases account's UnreservedConcurrentExecution below its minimum" | Remove the `RESERVED_CONCURRENCY` variable; the account's limit is too low to reserve any. |
| ❌ Database | `DATABASE_URL` in Parameter Store is wrong or the Neon project is suspended. Fix it, then restart the API. |
| ❌ Public address | Set the domain variables, or `PUBLIC_BASE_URL` in Parameter Store (option C). |
| ❌ Email: domain not verified | DKIM records missing or still propagating; SES can take up to 72 hours. |
| Site shows `{"error":{"code":"forbidden"...}}` | You're on the Lambda Function URL directly. Use the CloudFront address. |
| Customer emails don't arrive | SES is still in the sandbox (step 9), or they went to spam (add the DMARC record). The invoice/estimate page in the app shows whether each email was sent. |

## Removing everything

Delete the `shop` stack, then `shop-bootstrap`, in CloudFormation. The files and backups buckets are deliberately kept so customer records aren't lost by accident; empty and delete them yourself if you're sure. Delete the Neon project separately.

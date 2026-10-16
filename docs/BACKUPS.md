# Backups and restore

Customer records, invoices, and repair history live in the Neon Postgres database. Signed PDFs, signature images, and the logo live in the S3 files bucket. Both are protected, in layers.

## What protects what

| Layer | Covers | How often | Kept for | Where |
|---|---|---|---|---|
| Nightly dump | Entire database | Every night, 07:17 UTC (3:17 AM Eastern in summer) | Daily copies 35 days; first-of-month copies 400 days | S3 backups bucket (`daily/`, `monthly/`) |
| Neon restore window | Entire database, to any moment | Continuous | 6 hours on the free plan (7 days on Launch) | Neon |
| S3 versioning | Signed PDFs, signatures, logo | Every write | Current version forever; overwritten versions 30 days | S3 files bucket |
| CSV export (Phase 5) | Your own spreadsheet copy | When you choose | Yours | Your computer |

The 6-hour Neon window is too short on its own: a mistake noticed the next morning is already outside it. The nightly dump is the backup you rely on.

Safeguards built in:
- The backup job checks every dump before uploading: `pg_restore` must be able to read it, and the core tables (customers, vehicles, work orders, estimates, invoices, payments, signatures, audit log) must be in it. A bad dump fails the run instead of quietly replacing a good one.
- The backup job's AWS role can **add** files to the backups bucket but cannot read, list, or delete them. A leaked GitHub token can't destroy your backups.
- Both buckets are kept (`DeletionPolicy: Retain`) even if the AWS stack is deleted.
- The app never deletes stored documents. Signed versions are immutable.
- GitHub emails you when a scheduled backup run fails. Check that the repo owner's GitHub notification email is one you read.

## Turning on nightly backups

After the first successful deploy:
1. In the CloudFormation console open the `shop` stack's **Outputs** and copy `BackupRoleArn` and `BackupsBucketName`.
2. In GitHub: **Settings → Secrets and variables → Actions → Variables**, add `AWS_BACKUP_ROLE_ARN` and `BACKUP_BUCKET` with those values. (`DATABASE_URL` is already a secret from setup.)
3. **Actions → Backup → Run workflow.** When it turns green, its summary shows the file it wrote.
4. In the S3 console, open the backups bucket, then `daily/`: the file should be there.

## Restoring

Restore into a **new, empty database** first, check it, and only then point the app at it. Never restore on top of the live database.

### 1. Get the backup file
In the S3 console, open the backups bucket → `daily/` (or `monthly/`) → pick the newest file from **before** the problem → **Download**.

### 2. Make an empty database
In the Neon console: your project → **Databases → New database**, name it `restore_check`. Copy its connection string (Dashboard → Connection string, choose that database).

### 3. Restore
You need PostgreSQL client tools at least as new as the Neon server (`brew install postgresql@18` on a Mac, then follow brew's note to add it to your PATH). From the repo folder:
```bash
infra/scripts/restore.sh ~/Downloads/shop-2026-10-15T0717Z.dump "postgresql://USER:PASSWORD@HOST/restore_check?sslmode=require"
```
It refuses to run if the target database already has tables, then prints the schema version and record counts (customers, vehicles, work orders, invoices, payments) and the newest invoice date. Check those look right.

### 4. Switch the app over
Pick one:
- **Replace the database's contents** (keeps the same connection string): in Neon, rename the broken database to `shop_broken` and `restore_check` to the original name (`neondb` by default). Then restart the API (see "Restarting the API" in DEPLOYMENT.md).
- **Point the app at the restored database:** update `DATABASE_URL` in Parameter Store and in the GitHub secret to the `restore_check` connection string, then restart the API.

Then open the site, sign in, and check a recent customer and invoice. Keep the broken copy for a few days in case something needs to be copied across.

### Recent mistakes (within 6 hours)
Neon can rewind to any moment in the restore window: Neon console → **Restore** → choose a time just before the mistake. That's quicker and loses less than the nightly dump. Neon keeps a backup branch of the pre-restore state.

### Lost or overwritten files
In the S3 console, open the files bucket, turn on **Show versions**, find the file, and download or restore the earlier version.

## Practice once

Do a full restore into `restore_check` once after going live, then delete that database. A backup that has never been restored is a guess. This procedure was rehearsed during development: a dump of the demo data was verified, restored into an empty database (all record counts matched, schema at the current version, app's go-live checks passed against it), and the script correctly refused a second restore into the now non-empty database.

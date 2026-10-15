from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, EmailStr, Field, model_validator

from app.schemas.common import ShortText, _strip

Name = Annotated[str, BeforeValidator(_strip), Field(min_length=2, max_length=160)]


class RespondIn(BaseModel):
    decision: Literal["approved", "declined"]
    signer_name: Name
    agree: bool = False
    # Drawn signature as a PNG data URL from the signature pad.
    signature_image: Annotated[str, Field(max_length=600_000)] | None = None
    typed_signature: ShortText(160) = None
    note: ShortText(1000) = None


class QuestionIn(BaseModel):
    message: Annotated[str, BeforeValidator(_strip), Field(min_length=2, max_length=2000)]


class BookingIn(BaseModel):
    name: Name
    phone: ShortText(40) = None
    email: Annotated[EmailStr | None, BeforeValidator(_strip)] = None
    vehicle_year: Annotated[int, Field(ge=1900, le=2100)] | None = None
    vehicle_make: ShortText(60) = None
    vehicle_model: ShortText(80) = None
    mileage: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    requested_service: ShortText(200) = None
    preferred_date: date | None = None
    preferred_time: Literal["morning", "midday", "afternoon", "any"] | None = None
    concern: ShortText(3000) = None
    notes: ShortText(2000) = None
    # Honeypot: real visitors never see or fill this field.
    website: str | None = None

    @model_validator(mode="after")
    def contact(self):
        if not (self.phone or self.email):
            raise ValueError(
                "Enter a phone number or email so the shop can confirm your appointment."
            )
        return self


class ContactIn(BaseModel):
    name: Name
    phone: ShortText(40) = None
    email: Annotated[EmailStr | None, BeforeValidator(_strip)] = None
    message: Annotated[str, BeforeValidator(_strip), Field(min_length=2, max_length=3000)]
    website: str | None = None

    @model_validator(mode="after")
    def contact(self):
        if not (self.phone or self.email):
            raise ValueError("Enter a phone number or email so the shop can reply.")
        return self

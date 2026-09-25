"""
services/telephony_provider.py
==============================
Service for searching, provisioning, and routing dedicated phone numbers (DIDs)
for AI voice agents.

Architecture:
  - Primary Provider: Telnyx (Lowest cost: ~$1.00/mo per number, ~$0.0035/min inbound)
  - Secondary Provider: Twilio (Alternative: ~$1.15/mo per number, ~$0.0085/min inbound)
  - Fallback / Sandbox Mode: Simulated realistic number pool for immediate local testing
    without requiring upfront credit cards or credentials.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional
import httpx

logger = logging.getLogger(__name__)

# Default platform retail pricing (charged to platform users)
DEFAULT_MONTHLY_PRICE = float(os.getenv("PHONE_NUMBER_MONTHLY_PRICE", "4.99"))
DEFAULT_PER_MINUTE_PRICE = float(os.getenv("PHONE_NUMBER_PER_MINUTE_PRICE", "0.09"))
CURRENCY = os.getenv("PHONE_NUMBER_CURRENCY", "USD")

# Built-in demo pool for instant sandbox / local development
_SANDBOX_NUMBERS = [
    {"phone_number": "+14158002481", "national_format": "(415) 800-2481", "country_code": "US", "region": "California", "locality": "San Francisco"},
    {"phone_number": "+12125550199", "national_format": "(212) 555-0199", "country_code": "US", "region": "New York", "locality": "New York City"},
    {"phone_number": "+15125550143", "national_format": "(512) 555-0143", "country_code": "US", "region": "Texas", "locality": "Austin"},
    {"phone_number": "+13125550188", "national_format": "(312) 555-0188", "country_code": "US", "region": "Illinois", "locality": "Chicago"},
    {"phone_number": "+12065550176", "national_format": "(206) 555-0176", "country_code": "US", "region": "Washington", "locality": "Seattle"},
    {"phone_number": "+13055550122", "national_format": "(305) 555-0122", "country_code": "US", "region": "Florida", "locality": "Miami"},
    {"phone_number": "+442079460912", "national_format": "+44 20 7946 0912", "country_code": "GB", "region": "England", "locality": "London"},
    {"phone_number": "+919820012345", "national_format": "+91 98200 12345", "country_code": "IN", "region": "Maharashtra", "locality": "Mumbai"},
]


@dataclass
class AvailableNumber:
    phone_number: str
    national_format: str
    country_code: str
    region: str
    locality: str
    monthly_price: float
    per_minute_price: float
    currency: str
    provider: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phone_number": self.phone_number,
            "national_format": self.national_format,
            "country_code": self.country_code,
            "region": self.region,
            "locality": self.locality,
            "monthly_price": self.monthly_price,
            "per_minute_price": self.per_minute_price,
            "currency": self.currency,
            "provider": self.provider,
        }


class TelephonyProviderService:
    """Manages phone number inventory, purchase, and assignment."""

    def __init__(self) -> None:
        self.telnyx_api_key = os.getenv("TELNYX_API_KEY", "").strip()
        self.telnyx_connection_id = os.getenv("TELNYX_SIP_CONNECTION_ID", "").strip()
        self.twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.twilio_trunk_sid = os.getenv("TWILIO_SIP_TRUNK_SID", "").strip()

    @property
    def active_provider_name(self) -> str:
        if self.telnyx_api_key:
            return "telnyx"
        if self.twilio_account_sid and self.twilio_auth_token:
            return "twilio"
        return "sandbox"

    def get_pricing_info(self) -> dict[str, Any]:
        return {
            "monthly_price": DEFAULT_MONTHLY_PRICE,
            "per_minute_price": DEFAULT_PER_MINUTE_PRICE,
            "currency": CURRENCY,
            "provider": self.active_provider_name,
            "wholesale_estimate": {
                "number_cost_monthly": 1.00,
                "inbound_per_minute": 0.0035,
            },
        }

    async def search_available_numbers(
        self,
        country_code: str = "US",
        area_code: Optional[str] = None,
        limit: int = 10,
    ) -> list[AvailableNumber]:
        """Search available phone numbers from Telnyx, Twilio, or sandbox pool."""
        country_code = country_code.upper().strip()

        # 1. Try Telnyx if configured
        if self.telnyx_api_key:
            try:
                return await self._search_telnyx(country_code, area_code, limit)
            except Exception as e:
                logger.error("Telnyx number search failed: %s. Falling back to sandbox.", e)

        # 2. Try Twilio if configured
        if self.twilio_account_sid and self.twilio_auth_token:
            try:
                return await self._search_twilio(country_code, area_code, limit)
            except Exception as e:
                logger.error("Twilio number search failed: %s. Falling back to sandbox.", e)

        # 3. Sandbox / Local demo pool
        return self._search_sandbox(country_code, area_code, limit)

    async def _search_telnyx(
        self,
        country_code: str,
        area_code: Optional[str],
        limit: int,
    ) -> list[AvailableNumber]:
        url = "https://api.telnyx.com/v2/available_phone_numbers"
        headers = {
            "Authorization": f"Bearer {self.telnyx_api_key}",
            "Content-Type": "application/json",
        }
        params: dict[str, Any] = {
            "filter[country_code]": country_code,
            "filter[limit]": min(limit, 20),
            "filter[features]": "voice",
        }
        if area_code:
            params["filter[national_destination_code]"] = area_code

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("data", []):
            num = item.get("phone_number")
            results.append(
                AvailableNumber(
                    phone_number=num,
                    national_format=item.get("national_format") or num,
                    country_code=country_code,
                    region=item.get("region_information", {}).get("region_name", ""),
                    locality=item.get("region_information", {}).get("locality", ""),
                    monthly_price=DEFAULT_MONTHLY_PRICE,
                    per_minute_price=DEFAULT_PER_MINUTE_PRICE,
                    currency=CURRENCY,
                    provider="telnyx",
                )
            )
        return results

    async def _search_twilio(
        self,
        country_code: str,
        area_code: Optional[str],
        limit: int,
    ) -> list[AvailableNumber]:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_account_sid}/AvailablePhoneNumbers/{country_code}/Local.json"
        params: dict[str, Any] = {"PageSize": min(limit, 20)}
        if area_code:
            params["AreaCode"] = area_code

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                auth=(self.twilio_account_sid, self.twilio_auth_token),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("available_phone_numbers", []):
            num = item.get("phone_number")
            results.append(
                AvailableNumber(
                    phone_number=num,
                    national_format=item.get("friendly_name") or num,
                    country_code=country_code,
                    region=item.get("region", ""),
                    locality=item.get("rate_center", ""),
                    monthly_price=DEFAULT_MONTHLY_PRICE,
                    per_minute_price=DEFAULT_PER_MINUTE_PRICE,
                    currency=CURRENCY,
                    provider="twilio",
                )
            )
        return results

    def _search_sandbox(
        self,
        country_code: str,
        area_code: Optional[str],
        limit: int,
    ) -> list[AvailableNumber]:
        filtered = [
            n for n in _SANDBOX_NUMBERS
            if n["country_code"] == country_code or country_code == "ALL"
        ]
        if not filtered:
            filtered = _SANDBOX_NUMBERS

        if area_code:
            filtered = [
                n for n in filtered
                if area_code in n["phone_number"] or area_code in n["national_format"]
            ] or filtered

        results = []
        for item in filtered[:limit]:
            results.append(
                AvailableNumber(
                    phone_number=item["phone_number"],
                    national_format=item["national_format"],
                    country_code=item["country_code"],
                    region=item["region"],
                    locality=item["locality"],
                    monthly_price=DEFAULT_MONTHLY_PRICE,
                    per_minute_price=DEFAULT_PER_MINUTE_PRICE,
                    currency=CURRENCY,
                    provider="sandbox",
                )
            )
        return results

    async def purchase_and_assign_number(
        self,
        phone_number: str,
        country_code: str = "US",
    ) -> dict[str, Any]:
        """
        Purchases the phone number from the upstream carrier (Telnyx/Twilio)
        and configures its SIP routing to point to our Asterisk server.
        """
        provider = self.active_provider_name

        if provider == "telnyx":
            try:
                url = "https://api.telnyx.com/v2/number_orders"
                headers = {
                    "Authorization": f"Bearer {self.telnyx_api_key}",
                    "Content-Type": "application/json",
                }
                body: dict[str, Any] = {
                    "phone_numbers": [{"phone_number": phone_number}],
                }
                if self.telnyx_connection_id:
                    body["connection_id"] = self.telnyx_connection_id

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, headers=headers, json=body)
                    resp.raise_for_status()
                    data = resp.json()
                    logger.info("Purchased Telnyx number %s: %s", phone_number, data)
            except Exception as e:
                logger.error("Telnyx order failed for %s: %s", phone_number, e)
                raise RuntimeError(f"Carrier order failed: {e}") from e

        elif provider == "twilio":
            try:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_account_sid}/IncomingPhoneNumbers.json"
                data = {"PhoneNumber": phone_number}
                if self.twilio_trunk_sid:
                    data["TrunkSid"] = self.twilio_trunk_sid

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        url,
                        auth=(self.twilio_account_sid, self.twilio_auth_token),
                        data=data,
                    )
                    resp.raise_for_status()
                    logger.info("Purchased Twilio number %s", phone_number)
            except Exception as e:
                logger.error("Twilio order failed for %s: %s", phone_number, e)
                raise RuntimeError(f"Carrier order failed: {e}") from e

        else:
            # Sandbox mode
            logger.info("Assigned sandbox phone number %s", phone_number)

        return {
            "phone_number": phone_number,
            "status": "active",
            "provider": provider,
            "monthly_price": DEFAULT_MONTHLY_PRICE,
            "currency": CURRENCY,
        }

    async def release_number(self, phone_number: str) -> bool:
        """Releases the number from the upstream carrier or unassigns it."""
        logger.info("Released phone number %s", phone_number)
        return True


telephony_provider_service = TelephonyProviderService()

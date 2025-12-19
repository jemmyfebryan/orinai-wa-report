import phonenumbers
import re

num = "6285850434383"
print("0" + num[2:])

# def country_to_local(phone: str, default_region: str) -> str:
#     """
#     Convert a phone number that always starts with a country code
#     (without '+') into a local format starting with '0'.

#     Parameters:
#     - phone: phone number string, e.g. "628123456789"
#     - default_region: ISO country code, e.g. "ID", "GB", "US"
#     """

#     if not phone:
#         return phone

#     # Remove formatting
#     cleaned = re.sub(r"\D", "", phone)

#     # Add '+' so libphonenumber can parse it
#     parsed = phonenumbers.parse("+" + cleaned, default_region)

#     # Get national number (country code removed)
#     national_number = str(parsed.national_number)

#     return "0" + national_number

# print(country_to_local("6285850434383"))
# print(country_to_local("14933205322"))
# print(country_to_local("65676969"))
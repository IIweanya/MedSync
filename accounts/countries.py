"""International dialling codes for the phone-number field.

req1 §2 requires the country selector to support multiple countries rather than
hard-coding the United States.

The select is keyed on **ISO 3166-1 alpha-2 codes**, not dial codes. Dial codes are
not unique — Canada and the United States both use +1 — so using them as option
values would make two options match on re-render, and the browser would silently
snap the user's choice to whichever came last. ISO codes keep every option value
distinct and round-trip correctly after a validation error.

Flag emoji are derived from the ISO code (regional indicator symbols) rather than
typed by hand, so there is no way for a flag and a country to drift apart.
"""

# (iso_alpha2, country_name, dial_code) — sorted by country name.
COUNTRIES = [
    ('AF', 'Afghanistan', '+93'),
    ('AL', 'Albania', '+355'),
    ('DZ', 'Algeria', '+213'),
    ('AR', 'Argentina', '+54'),
    ('AM', 'Armenia', '+374'),
    ('AU', 'Australia', '+61'),
    ('AT', 'Austria', '+43'),
    ('AZ', 'Azerbaijan', '+994'),
    ('BH', 'Bahrain', '+973'),
    ('BD', 'Bangladesh', '+880'),
    ('BY', 'Belarus', '+375'),
    ('BE', 'Belgium', '+32'),
    ('BJ', 'Benin', '+229'),
    ('BO', 'Bolivia', '+591'),
    ('BW', 'Botswana', '+267'),
    ('BR', 'Brazil', '+55'),
    ('BG', 'Bulgaria', '+359'),
    ('BF', 'Burkina Faso', '+226'),
    ('KH', 'Cambodia', '+855'),
    ('CM', 'Cameroon', '+237'),
    ('CA', 'Canada', '+1'),
    ('CL', 'Chile', '+56'),
    ('CN', 'China', '+86'),
    ('CO', 'Colombia', '+57'),
    ('CR', 'Costa Rica', '+506'),
    ('CI', 'Côte d’Ivoire', '+225'),
    ('HR', 'Croatia', '+385'),
    ('CY', 'Cyprus', '+357'),
    ('CZ', 'Czechia', '+420'),
    ('DK', 'Denmark', '+45'),
    ('EC', 'Ecuador', '+593'),
    ('EG', 'Egypt', '+20'),
    ('ET', 'Ethiopia', '+251'),
    ('FI', 'Finland', '+358'),
    ('FR', 'France', '+33'),
    ('DE', 'Germany', '+49'),
    ('GH', 'Ghana', '+233'),
    ('GR', 'Greece', '+30'),
    ('GT', 'Guatemala', '+502'),
    ('HK', 'Hong Kong', '+852'),
    ('HU', 'Hungary', '+36'),
    ('IS', 'Iceland', '+354'),
    ('IN', 'India', '+91'),
    ('ID', 'Indonesia', '+62'),
    ('IQ', 'Iraq', '+964'),
    ('IE', 'Ireland', '+353'),
    ('IL', 'Israel', '+972'),
    ('IT', 'Italy', '+39'),
    ('JP', 'Japan', '+81'),
    ('JO', 'Jordan', '+962'),
    ('KE', 'Kenya', '+254'),
    ('KW', 'Kuwait', '+965'),
    ('LB', 'Lebanon', '+961'),
    ('LY', 'Libya', '+218'),
    ('MY', 'Malaysia', '+60'),
    ('ML', 'Mali', '+223'),
    ('MT', 'Malta', '+356'),
    ('MX', 'Mexico', '+52'),
    ('MA', 'Morocco', '+212'),
    ('MZ', 'Mozambique', '+258'),
    ('NA', 'Namibia', '+264'),
    ('NP', 'Nepal', '+977'),
    ('NL', 'Netherlands', '+31'),
    ('NZ', 'New Zealand', '+64'),
    ('NE', 'Niger', '+227'),
    ('NG', 'Nigeria', '+234'),
    ('NO', 'Norway', '+47'),
    ('OM', 'Oman', '+968'),
    ('PK', 'Pakistan', '+92'),
    ('PA', 'Panama', '+507'),
    ('PE', 'Peru', '+51'),
    ('PH', 'Philippines', '+63'),
    ('PL', 'Poland', '+48'),
    ('PT', 'Portugal', '+351'),
    ('QA', 'Qatar', '+974'),
    ('RO', 'Romania', '+40'),
    ('RU', 'Russia', '+7'),
    ('RW', 'Rwanda', '+250'),
    ('SA', 'Saudi Arabia', '+966'),
    ('SN', 'Senegal', '+221'),
    ('RS', 'Serbia', '+381'),
    ('SG', 'Singapore', '+65'),
    ('SK', 'Slovakia', '+421'),
    ('SI', 'Slovenia', '+386'),
    ('SO', 'Somalia', '+252'),
    ('ZA', 'South Africa', '+27'),
    ('KR', 'South Korea', '+82'),
    ('ES', 'Spain', '+34'),
    ('LK', 'Sri Lanka', '+94'),
    ('SD', 'Sudan', '+249'),
    ('SE', 'Sweden', '+46'),
    ('CH', 'Switzerland', '+41'),
    ('TW', 'Taiwan', '+886'),
    ('TZ', 'Tanzania', '+255'),
    ('TH', 'Thailand', '+66'),
    ('TN', 'Tunisia', '+216'),
    ('TR', 'Türkiye', '+90'),
    ('UG', 'Uganda', '+256'),
    ('UA', 'Ukraine', '+380'),
    ('AE', 'United Arab Emirates', '+971'),
    ('GB', 'United Kingdom', '+44'),
    ('US', 'United States', '+1'),
    ('UY', 'Uruguay', '+598'),
    ('UZ', 'Uzbekistan', '+998'),
    ('VE', 'Venezuela', '+58'),
    ('VN', 'Vietnam', '+84'),
    ('YE', 'Yemen', '+967'),
    ('ZM', 'Zambia', '+260'),
    ('ZW', 'Zimbabwe', '+263'),
]

_REGIONAL_INDICATOR_OFFSET = 0x1F1E6 - ord('A')


def flag(iso_code):
    """Return the flag emoji for an ISO 3166-1 alpha-2 code."""
    return ''.join(chr(ord(c) + _REGIONAL_INDICATOR_OFFSET) for c in iso_code.upper())


# Choices for the country <select>: ISO code as value, flag + name + dial as label.
COUNTRY_CHOICES = [
    (iso, f'{flag(iso)} {name} ({dial})') for iso, name, dial in COUNTRIES
]

DIAL_BY_ISO = {iso: dial for iso, _, dial in COUNTRIES}

NAME_BY_ISO = {iso: name for iso, name, _ in COUNTRIES}

# Compact label for the closed select, where horizontal space is tight.
SHORT_LABEL_BY_ISO = {iso: f'{flag(iso)} {dial}' for iso, _, dial in COUNTRIES}

# Preserves the previous default rather than silently changing it. req1 only
# forbids the US being the *only* option, not the initial one.
DEFAULT_COUNTRY = 'US'

# ITU-T E.164 caps a full number at 15 digits including the country code, so the
# national part is always shorter than that.
MAX_NATIONAL_DIGITS = 14
MIN_NATIONAL_DIGITS = 6

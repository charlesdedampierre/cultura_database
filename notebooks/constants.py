"""Shared definitions used across notebooks.

- Western / non-Western source classification (countries, Wikipedia languages).
- Continent grouping (with Latin-America override for cross-database comparisons).
- Cultural worlds → Cliopatria polity lists.
"""

WESTERN_COUNTRIES = [
    'United States', 'Washington, D.C.', 'Germany', 'France', 'Poland',
    'Netherlands', 'Kingdom of the Netherlands', 'United Kingdom', 'Wales',
    'Italy', 'Kingdom of Italy', 'Spain', 'Sweden', 'Norway', 'Finland',
    'Denmark', 'Faroe Islands', 'Austria', 'Belgium', 'Switzerland',
    'Portugal', 'Czech Republic', 'Slovakia', 'Greece', 'Hungary',
    'Ireland', 'Canada', 'Australia', 'New Zealand', 'Romania', 'Croatia',
    'Serbia', 'Slovenia', 'Lithuania', 'Latvia', 'Estonia', 'Bulgaria',
    'Iceland', 'Luxembourg', 'Liechtenstein', 'Andorra', 'Cyprus',
    'Vatican City', 'Weimar Republic', 'German Reich',
]

WESTERN_WIKIPEDIA_LANGUAGES = [
    'en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'sv', 'no', 'nb', 'nn',
    'fi', 'da', 'is', 'fo', 'ga', 'gd', 'cy', 'kw', 'gv', 'br', 'co', 'oc',
    'ca', 'eu', 'gl', 'ast', 'an', 'ext', 'lad', 'mwl', 'rm', 'fur', 'lij',
    'lmo', 'nap', 'pms', 'scn', 'vec', 'sc', 'lb', 'wa', 'fy', 'li', 'nds',
    'vls', 'frr', 'stq', 'dsb', 'hsb', 'ksh', 'bar', 'pdc', 'pfl', 'gsw',
    'frp', 'csb', 'szl', 'cs', 'sk', 'sl', 'hr', 'bs', 'sr', 'sh', 'mk',
    'bg', 'ro', 'mo', 'hu', 'et', 'lv', 'lt', 'el', 'grc', 'la', 'simple',
    'eo',
]

NON_WESTERN_WIKIPEDIA_LANGUAGES = [
    'ar', 'arz', 'ru', 'uk', 'be', 'be-tarask', 'kk', 'ky', 'uz', 'tg',
    'tk', 'mn', 'ja', 'zh', 'zh-yue', 'yue', 'wuu', 'hak', 'lzh', 'ko',
    'id', 'ms', 'jv', 'su', 'min', 'ace', 'vi', 'th', 'lo', 'km', 'my',
    'tr', 'az', 'azb', 'ckb', 'fa', 'he', 'ur', 'pnb', 'ps', 'sd', 'hi',
    'bn', 'as', 'or', 'ta', 'te', 'ml', 'kn', 'mr', 'gu', 'pa', 'ne', 'si',
    'dv', 'ka', 'hy', 'yi', 'tl', 'ceb', 'war', 'ig', 'yo', 'ha', 'sw',
    'zu', 'xh', 'st', 'sn', 'ny', 'rw', 'lg', 'tn', 'ts', 've', 'nso',
    'ss', 'om', 'so', 'ti', 'am', 'tw', 'ee', 'fon', 'kg', 'lua', 'sg',
    'ln', 'mg', 'kab', 'sat', 'bho', 'mai', 'new', 'anp', 'doi', 'ks',
    'sa', 'pi', 'dty', 'awa', 'shn', 'tcy', 'kok',
]

CONTINENTS = ['Europe', 'Asia', 'Africa', 'North America', 'Latin America', 'Oceania']

LATIN_AMERICAN_COUNTRIES = [
    'Mexico', 'Belize', 'Costa Rica', 'Cuba', 'Dominica', 'Dominican Republic',
    'El Salvador', 'Guatemala', 'Haiti', 'Honduras', 'Jamaica', 'Nicaragua',
    'Panama', 'Antigua and Barbuda', 'Aruba', 'Barbados', 'Curaçao',
    'Grenada', 'Saint Kitts and Nevis', 'Saint Lucia',
    'Saint Vincent and the Grenadines', 'The Bahamas', 'Trinidad and Tobago',
    'Argentina', 'Bolivia', 'Brazil', 'Chile', 'Colombia', 'Ecuador',
    'Guyana', 'Paraguay', 'Peru', 'Suriname', 'Uruguay', 'Venezuela',
]

WORLDS = {
    'Chinese world': [
        'Shang Dynasty', 'Zhou Dynasty', 'Qin Dynasty', 'Han Dynasty', 'Xin Dynasty',
        'Western Jin', 'Eastern Jin', 'Liu Song Dynasty', 'Liang Dynasty', 'Chen Dynasty',
        'Northern Wei', 'Eastern Wei', 'Western Wei', 'Northern Zhou', 'Northern Qi',
        'Sui Dynasty', 'Tang Dynasty', 'Five Dynasties and Ten Kingdoms',
        'Northern Song', 'Southern Song', 'Liao Dynasty', 'Western Xia',
        'Yuan Dynasty', 'Ming Dynasty', 'Qing Dynasty',
    ],
    'Greek world': [
        'Greek City-States', 'Greek Colonies', 'Greek Dark Ages',
        'Athenian Coalition', 'Second Athenian League',
        'Antigonid Dynasty', 'Antigonid Macedonia', 'Macedonian Empire',
        'Ptolemaic Kingdom', 'Seleucid Empire',
        'Achaean League', 'Despotate of Epirus',
        'Duchy of Athens', 'Principality of Achaea',
        'Byzantine Empire', 'Indo-Greeks',
    ],
    'Muslim world': [
        'Rashidun Caliphate', 'Umayyad Caliphate', 'Abbasid Caliphate',
        'Caliphate of Córdoba', 'Fatimid Caliphate', 'Almohad Caliphate',
        'Sokoto Caliphate', 'Ayyubid Sultanate', 'Mamluk Sultanate', 'Mamluk Dynasty',
        'Almoravid Dynasty', 'Idrisids', 'Aghlabid Dynasty', 'Tahirid Sultanate',
        'Saffarid Dynasty', 'Samanid Empire', 'Buyid Dynasty', 'Ghaznavid Empire',
        'Great Seljuk Empire', 'Seljuk Dynasty', 'Sultanate of Rum', 'Ilkhanate',
        'Khwarezmid Empire', 'Khwarezmid Dynasty', 'Timurid Empire', 'Jalayirid Sultanate',
        'Safavid Dynasty', 'Ottoman Empire', 'Ottoman Tripolitania',
        'Hafsid Dynasty', 'Marinid Sultanate', 'Wattasid dynasty', 'Saadi Sultanate',
        'Delhi Sultanate', 'Bahmani Sultanate', 'Mughal Empire',
        'Islamic Republic of Iran', 'Islamic Republic of Pakistan',
    ],
    'Japan': [
        'Asuka Japan', 'Nara Japan', 'Heian Japan',
        'Kamakura Shogunate', 'Ashikaga Shogunate',
        'Warring States Japan', 'Tokugawa Shogunate',
        'Empire of Japan', 'Japan',
    ],
    'Korea': [
        'Gojoseon', 'Goguryeo', 'Baekje', 'Silla', 'Unified Silla',
        'Balhae', 'Hubaekje', 'Goryeo', 'Joseon',
        'Korean Empire', 'Republic of Korea', "Democratic People's Republic of Korea",
    ],
    'India': [
        'Maurya Empire', 'Gupta Empire',
        'Magadha - Haryanka dynasty', 'Magadha - Shaishunaga dynasty',
        'Kushan Empire', 'Western Kushans', 'Eastern Kushans',
        'Satavahana Dynasty', 'Late Pallava Empire',
        'Early Cholas', 'Chola Empire',
        'Pandya Dynasty', 'Pandya Empire', 'Early Pandyas',
        'Chalukya Dynasty', 'Western Chalukya Empire',
        'Rashtrakuta Dynasty', 'Pala Empire', 'Sena Dynasty',
        'Hoysala Kingdom', 'Kakatiya Dynasty', 'Vijayanagara Empire',
        'Maratha Empire', 'Sikh Empire', 'Mughal Empire', 'Republic of India',
    ],
}

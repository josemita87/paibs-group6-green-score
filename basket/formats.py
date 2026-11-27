"""Name and ingredient evidence that a product has another format than its family's use.

The pilot's ambiguous and unacceptable pairs came from products that share a
family tag but not its use: yogurt drinks among spoonable yogurts, cooking coconut
milk among cereal drinks, porridge and bars among cold-milk cereals. This module
flags that evidence with keyword rules so that pair sampling can use it.

Evidence is a sampling signal. It is not a label, it misses products whose text
says nothing, and it flags some products wrongly.
"""
import re

from basket.comparable import normalize_key

COCONUT = r'(?:coco|kokos|kokosnuss|coconut|cocco|kokosnoot|noix de coco)'
COCONUT_COOKING_PERCENT = 25   # cereal drinks in the catalog hold 2 to 9 % coconut

_YOGURT_DRINK_NAME = re.compile(
    r'\b(a boire|aboire|drink|drinks|drinkable|bebible|para beber|beber|trink\w*|da bere|bevibile|'
    r'liquide|liquido|kefir|lassi|gourde|pouch|squashums)\b')
_YOGURT_DRINK_BRAND = re.compile(r'\b(yop|actimel|danacol)\b')
_PLANT_COOKING_NAME = re.compile(
    r'\b(creme|cream|crema|cuisine|cooking|kochen|cocinar|sahne|panna|powder|pulver|poudre)\b')
_COCONUT_MILK_NAME = re.compile(
    r'\b(lait de coco|kokosmilch|coconut milk|leche de coco|latte di cocco|kokosmelk|lait coco)\b')
_DRINK_WORD = re.compile(r'\b(drink|boisson|bebida|beverage|bevanda|getrank|drank|beguda)\b')
_PLANT_OTHER_NAME = re.compile(
    r'\b(dessert|yaourt|yogurt|yogur|joghurt|pudding|nata de coco|juice|jus|zumo|saft|'
    r'red fruits|fruits rouges)\b')
_CEREAL_COOKING_NAME = re.compile(r'\b(porridge|a cuire|semoule|polenta|farine|flour|harina|mehl)\b')
_CEREAL_SNACK_NAME = re.compile(
    r'\b(barre|barres|bar|bars|barrita|barritas|riegel|barretta|barrette|galette|galettes|'
    r'crackers?|snack|aperitif|bread|pain)\b')
_CEREAL_BRAN_NAME = re.compile(r'\b(son|bran|salvado|kleie|crusca|germe|germen|keime)\b')
_CEREAL_BRAN_FLAKES = re.compile(r'\b(all bran|flakes|petales|muesli|fibre|fibres)\b')
_COCONUT_PERCENT = re.compile(rf'{COCONUT}\w*(?: \w+){{0,3}}? (\d{{1,3}})(?: \d)?(?= |$)')


def coconut_percent(ingredients_text):
    """Largest percentage stated right after a coconut ingredient, or None."""
    values = [int(match.group(1))
              for match in _COCONUT_PERCENT.finditer(normalize_key(ingredients_text))]
    values = [value for value in values if value <= 100]
    return max(values) if values else None


def format_evidence(row) -> list[str]:
    """Reasons to think the product does not have the format its family's use assumes."""
    name = normalize_key(row['name'])
    family, evidence = row['family'], []
    if family == 'yogurts':
        if _YOGURT_DRINK_NAME.search(name):
            evidence.append('drink_or_pouch_name')
        if _YOGURT_DRINK_BRAND.search(f"{name} {normalize_key(row['brands'])}"):
            evidence.append('drink_brand')
    elif family == 'plant_based_milk_alternatives':
        percent = coconut_percent(row['ingredients_text'])
        if percent is not None and percent >= COCONUT_COOKING_PERCENT:
            evidence.append('coconut_25_percent_or_more')
        if _PLANT_COOKING_NAME.search(name):
            evidence.append('cream_cooking_or_powder_name')
        if _COCONUT_MILK_NAME.search(name) and not _DRINK_WORD.search(name):
            evidence.append('coconut_milk_name')
        if _PLANT_OTHER_NAME.search(name):
            evidence.append('dessert_or_juice_name')
    elif family == 'breakfast_cereals':
        if _CEREAL_COOKING_NAME.search(name):
            evidence.append('porridge_or_flour_name')
        if _CEREAL_SNACK_NAME.search(name):
            evidence.append('bar_or_snack_name')
        if _CEREAL_BRAN_NAME.search(name) and not _CEREAL_BRAN_FLAKES.search(name):
            evidence.append('bran_or_germ_name')
    return evidence

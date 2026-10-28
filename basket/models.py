"""Pydantic models for the user's basket (pipeline step 1).

The models validate what the user entered and record the catalog evidence each
item relies on. They do not check nutritional constraints, apply dietary
preferences or infer missing catalog data; those are later pipeline steps.
"""
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field, model_validator

CanonicalUnit = Literal['g', 'ml']
NUTRIENTS = ('proteins', 'sugars', 'salt')


class Unit(str, Enum):
    """Units the input flow accepts.

    The raw catalog records product quantities only in ``g`` or ``ml``; ``kg`` and
    ``l`` are exact decimal multiples of those. Counts, pieces, ounces and other
    free-text units found in the source ``quantity`` field are not supported.
    """

    GRAM = 'g'
    KILOGRAM = 'kg'
    MILLILITRE = 'ml'
    LITRE = 'l'


CANONICAL: dict[Unit, tuple[CanonicalUnit, int]] = {
    Unit.GRAM: ('g', 1),
    Unit.KILOGRAM: ('g', 1000),
    Unit.MILLILITRE: ('ml', 1),
    Unit.LITRE: ('ml', 1000),
}


def to_canonical(quantity: float, unit: Unit) -> tuple[float, CanonicalUnit]:
    """Express a quantity in the catalog's base unit (g or ml) without rounding."""
    base, factor = CANONICAL[Unit(unit)]
    return quantity * factor, base


class DietaryPreference(str, Enum):
    """Preferences the later filter step (9) is planned to enforce.

    Each value names the raw catalog evidence it would rely on. Declaring a
    preference here records the request only; nothing filters products yet.
    """

    VEGAN = 'vegan'
    VEGETARIAN = 'vegetarian'
    PALM_OIL_FREE = 'palm_oil_free'
    ORGANIC = 'organic'
    GLUTEN_FREE = 'gluten_free'


PREFERENCE_EVIDENCE: dict[DietaryPreference, str] = {
    DietaryPreference.VEGAN: 'ingredients_analysis_tags contains en:vegan',
    DietaryPreference.VEGETARIAN: 'ingredients_analysis_tags contains en:vegetarian',
    DietaryPreference.PALM_OIL_FREE: 'ingredients_analysis_tags contains en:palm-oil-free',
    DietaryPreference.ORGANIC: 'labels_tags contains en:organic',
    DietaryPreference.GLUTEN_FREE: 'labels_tags contains en:no-gluten',
}


class ProductRef(BaseModel):
    """A product selected from the pinned catalog, with the raw evidence available for it.

    Availability flags report whether a raw numeric value exists. They are not
    validated, normalized or comparable values.
    """

    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1, description='Barcode as stored in the catalog')
    name: Optional[str] = Field(None, description='Main product name; None when the source has none')
    brands: Optional[str] = None
    catalog_unit: Optional[CanonicalUnit] = Field(
        None, description='Raw product_quantity_unit; None when the source does not record it')
    nutrient_100g_available: dict[str, bool] = Field(
        description='Whether a nonnegative numeric raw value exists under the source "100g" key')
    environmental_score_available: bool = Field(
        description='Whether a numeric exported environmental score exists; not a comparable context')


class BasketItem(BaseModel):
    """One basket position: a catalog product, a quantity in a supported unit and a lock flag."""

    model_config = ConfigDict(frozen=True)

    product: ProductRef
    quantity: float = Field(gt=0, allow_inf_nan=False)
    unit: Unit
    locked: bool = Field(False, description='Locked products must stay unchanged by later steps')

    @computed_field
    @property
    def canonical_quantity(self) -> float:
        return to_canonical(self.quantity, self.unit)[0]

    @computed_field
    @property
    def canonical_unit(self) -> CanonicalUnit:
        return to_canonical(self.quantity, self.unit)[1]

    @computed_field
    @property
    def unit_basis(self) -> Literal['verified', 'unverified']:
        """'verified' only when the catalog records the same base unit; never inferred."""
        return 'verified' if self.product.catalog_unit == self.canonical_unit else 'unverified'

    @model_validator(mode='after')
    def unit_must_match_known_catalog_basis(self):
        known = self.product.catalog_unit
        if known is not None and known != self.canonical_unit:
            raise ValueError(
                f'product {self.product.code} is recorded in {known}; '
                f'{self.unit.value} is a {"volume" if self.canonical_unit == "ml" else "mass"} unit '
                'and is not compatible')
        return self


class NutritionalConstraints(BaseModel):
    """Whole-basket nutritional targets. Step 1 records them; no component checks them yet."""

    min_total_proteins_g: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    max_total_sugars_g: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    max_total_salt_g: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    enforcement: Literal['declared_not_checked'] = Field(
        'declared_not_checked',
        description='Constraints are stored only; checking them is planned for steps 9-10')

    def declared(self) -> dict[str, float]:
        return {name: value for name, value in self.model_dump().items()
                if name != 'enforcement' and value is not None}


class Preferences(BaseModel):
    """Dietary preferences. Step 1 records them; filtering is planned for step 9."""

    dietary: list[DietaryPreference] = Field(default_factory=list)
    enforcement: Literal['declared_not_checked'] = 'declared_not_checked'

    @model_validator(mode='after')
    def no_duplicates(self):
        if len(set(self.dietary)) != len(self.dietary):
            raise ValueError('dietary preferences must not repeat')
        return self


class Basket(BaseModel):
    """Structured basket for later pipeline steps. Contains inputs, not recommendations."""

    schema_version: Literal[1] = 1
    catalog_revision: str = Field(min_length=1)
    catalog_sha256: str = Field(min_length=1)
    items: list[BasketItem] = Field(min_length=1)
    max_substitutions: int = Field(ge=0)
    preferences: Preferences = Field(default_factory=Preferences)
    constraints: NutritionalConstraints = Field(default_factory=NutritionalConstraints)

    @computed_field
    @property
    def substitutable_positions(self) -> int:
        return sum(not item.locked for item in self.items)

    @computed_field
    @property
    def effective_max_substitutions(self) -> int:
        """The declared limit capped by the unlocked positions; the declared value is kept as well."""
        return min(self.max_substitutions, self.substitutable_positions)

    @model_validator(mode='after')
    def one_position_per_product(self):
        codes = [item.product.code for item in self.items]
        duplicates = sorted({code for code in codes if codes.count(code) > 1})
        if duplicates:
            raise ValueError(f'each product may appear once; duplicated: {", ".join(duplicates)}')
        return self


class ItemRequest(BaseModel):
    """Unvalidated user entry resolved by ``build_basket``; errors surface with the item index."""

    code: str
    quantity: float
    unit: Unit
    locked: bool = False


class BasketInputError(ValueError):
    """All validation problems found in one pass, as readable messages."""

    def __init__(self, errors: list[str]):
        super().__init__('; '.join(errors))
        self.errors = errors


def format_errors(error: ValidationError) -> list[str]:
    messages = []
    for item in error.errors():
        location = '.'.join(str(part) for part in item['loc'])
        message = item['msg'].removeprefix('Value error, ')
        messages.append(f'{location}: {message}' if location else message)
    return messages


def build_basket(catalog, requests: list[ItemRequest], max_substitutions: int,
                 preferences: Optional[Preferences] = None,
                 constraints: Optional[NutritionalConstraints] = None) -> Basket:
    """Resolve user entries against the catalog and validate the whole basket.

    Raises ``BasketInputError`` listing every unknown product and invalid value.
    """
    errors: list[str] = []
    items: list[BasketItem] = []
    for index, request in enumerate(requests, start=1):
        product = catalog.get(request.code)
        if product is None:
            errors.append(f'item {index}: unknown barcode {request.code!r} in the pinned catalog')
            continue
        try:
            items.append(BasketItem(product=product, quantity=request.quantity,
                                    unit=request.unit, locked=request.locked))
        except ValidationError as exc:
            errors.extend(f'item {index}: {message}' for message in format_errors(exc))
    if errors:
        raise BasketInputError(errors)
    try:
        return Basket(catalog_revision=catalog.revision, catalog_sha256=catalog.sha256,
                      items=items, max_substitutions=max_substitutions,
                      preferences=preferences or Preferences(),
                      constraints=constraints or NutritionalConstraints())
    except ValidationError as exc:
        raise BasketInputError(format_errors(exc)) from exc

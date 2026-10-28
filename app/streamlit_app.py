"""Minimal basket input flow (pipeline step 1).

Run from the repository root: ``streamlit run app/streamlit_app.py``.
Only input and validation are implemented; recommendations, nutritional checks
and optimization are later steps and are not available in this interface.
"""
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from basket.catalog import Catalog  # noqa: E402
from basket.models import (  # noqa: E402
    PREFERENCE_EVIDENCE, BasketInputError, BasketItem, DietaryPreference, ItemRequest,
    NutritionalConstraints, Preferences, Unit, build_basket, format_errors,
)

NOT_IMPLEMENTED = ('Recommendations, nutritional constraint checks, preference filtering and '
                   'optimization are not implemented. This screen only validates inputs.')


@st.cache_resource(show_spinner='Loading the pinned catalog...')
def load_catalog() -> Catalog:
    return Catalog.load(ROOT)


def label(product) -> str:
    name = html.unescape(product.name) if product.name else '(no name in source)'
    brands = f' — {html.unescape(product.brands)}' if product.brands else ''
    basis = product.catalog_unit or 'unit unknown'
    return f'{name}{brands} [{product.code}] · {basis}'


def show_product(product) -> None:
    st.markdown(f'**{html.unescape(product.name) if product.name else "(no name in source)"}**')
    st.write({
        'barcode': product.code,
        'brands': html.unescape(product.brands) if product.brands else None,
        'catalog unit basis': product.catalog_unit or 'not recorded in source (compatibility cannot be verified)',
        'raw 100g value present': {k: ('yes' if v else 'missing')
                                   for k, v in product.nutrient_100g_available.items()},
        'exported environmental score present': 'yes' if product.environmental_score_available else 'missing',
    })
    st.caption('Presence of a raw value is not a validated or comparable value.')


def sidebar() -> tuple[int, Preferences, NutritionalConstraints]:
    st.sidebar.header('Basket settings')
    max_substitutions = int(st.sidebar.number_input(
        'Maximum number of substitutions', min_value=0, value=3, step=1))
    st.sidebar.subheader('Dietary preferences')
    st.sidebar.caption('Declared only. Filtering by preference is planned for step 9.')
    dietary = st.sidebar.multiselect(
        'Preferences', [p.value for p in DietaryPreference],
        format_func=lambda v: f'{v} (evidence: {PREFERENCE_EVIDENCE[DietaryPreference(v)]})')
    st.sidebar.subheader('Nutritional constraints (whole basket)')
    st.sidebar.caption('Declared only. Nothing checks these totals yet (planned for steps 9-10).')
    values = {}
    for field, text in (('min_total_proteins_g', 'Minimum total proteins (g)'),
                        ('max_total_sugars_g', 'Maximum total sugars (g)'),
                        ('max_total_salt_g', 'Maximum total salt (g)')):
        if st.sidebar.checkbox(f'Set {text.lower()}', key=f'enable_{field}'):
            values[field] = st.sidebar.number_input(text, min_value=0.0, value=0.0, step=1.0,
                                                    key=f'value_{field}')
    return (max_substitutions,
            Preferences(dietary=[DietaryPreference(v) for v in dietary]),
            NutritionalConstraints(**values))


def select_product(catalog: Catalog):
    mode = st.radio('Find a product', ('Search by name or brand', 'Enter barcode'), horizontal=True)
    if mode == 'Enter barcode':
        code = st.text_input('Barcode', key='barcode')
        if not code.strip():
            return None
        product = catalog.get(code)
        if product is None:
            st.error(f'Unknown barcode {code.strip()!r}: not in the pinned catalog '
                     f'({len(catalog):,} products, revision {catalog.revision[:8]}).')
        return product
    query = st.text_input('Search', key='query', placeholder='e.g. yogurt')
    if not query.strip():
        return None
    results = catalog.search(query, limit=25)
    if not results:
        st.warning(f'No product name or brand contains {query.strip()!r}.')
        return None
    return st.selectbox(f'Matching products (first {len(results)})', results, format_func=label)


def add_item_form(product) -> None:
    columns = st.columns(3)
    quantity = columns[0].number_input('Quantity', min_value=0.0, value=100.0, step=10.0)
    unit = columns[1].selectbox('Unit', [u.value for u in Unit],
                                help='Only g, kg, ml and l are supported; the catalog records g or ml.')
    locked = columns[2].checkbox('Lock (never substitute)')
    if st.button('Add to basket', disabled=product is None):
        try:
            BasketItem(product=product, quantity=quantity, unit=Unit(unit), locked=locked)
        except ValidationError as exc:
            for message in format_errors(exc):
                st.error(message)
            return
        st.session_state.entries.append(
            ItemRequest(code=product.code, quantity=quantity, unit=Unit(unit), locked=locked))
        st.success(f'Added {label(product)}')


def basket_table(catalog: Catalog) -> None:
    st.subheader('Basket')
    entries: list[ItemRequest] = st.session_state.entries
    if not entries:
        st.info('The basket is empty. Add at least one product.')
        return
    for index, entry in enumerate(entries):
        product = catalog.get(entry.code)
        columns = st.columns((5, 2, 2, 1))
        columns[0].write(label(product) if product else f'unknown barcode {entry.code}')
        columns[1].write(f'{entry.quantity:g} {entry.unit.value}')
        locked = columns[2].checkbox('Locked', value=entry.locked, key=f'locked_{index}_{entry.code}')
        if locked != entry.locked:
            entries[index] = entry.model_copy(update={'locked': locked})
        if columns[3].button('Remove', key=f'remove_{index}_{entry.code}'):
            entries.pop(index)
            st.rerun()


def main() -> None:
    st.set_page_config(page_title='Basket Optimizer — basket input')
    st.title('Basket Optimizer: basket input (step 1)')
    st.caption(NOT_IMPLEMENTED)
    if 'entries' not in st.session_state:
        st.session_state.entries = []

    catalog = load_catalog()
    max_substitutions, preferences, constraints = sidebar()

    st.subheader('Add a product')
    product = select_product(catalog)
    if product is not None:
        show_product(product)
    add_item_form(product)

    basket_table(catalog)

    st.subheader('Validated basket')
    if st.button('Build basket', disabled=not st.session_state.entries):
        try:
            basket = build_basket(catalog, st.session_state.entries, max_substitutions,
                                  preferences, constraints)
        except BasketInputError as exc:
            for message in exc.errors:
                st.error(message)
        else:
            unverified = [item.product.code for item in basket.items if item.unit_basis == 'unverified']
            if unverified:
                st.warning('Unit compatibility could not be verified for: ' + ', '.join(unverified)
                           + '. The source records no unit for these products; none was inferred.')
            st.success(f'Basket is valid: {len(basket.items)} item(s), '
                       f'{basket.substitutable_positions} substitutable, '
                       f'up to {basket.effective_max_substitutions} change(s).')
            st.caption('Preferences and nutritional constraints are declared, not checked. '
                       + NOT_IMPLEMENTED)
            payload = basket.model_dump_json(indent=2)
            st.json(payload)
            st.download_button('Download basket JSON', payload, 'basket.json', 'application/json')


if __name__ == '__main__':
    main()

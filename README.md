# Basket Optimizer

Prototipo de investigación: mejorar una cesta de compra mediante sustituciones
aceptables, respetando preferencias y un máximo de cambios.

**Estado:** diseño definido y muestra de datos conservada. El recomendador, su
entrenamiento, el optimizador y la interfaz todavía no están implementados.

Ejemplo de uso previsto: «Mejora el indicador ambiental de mi cesta, mantén un
mínimo de proteína y cambia como máximo tres productos».

## Diseño

[Pipeline técnico, entrenamiento y evaluación](docs/PIPELINE.md).
El núcleo previsto es un encoder multilingüe ajustado con ejemplos de sustitución
más optimización discreta. Las explicaciones se construirán con los datos de cada
comparación; no hace falta una API de chat.

## Contenido

- `data/`: muestra OFF de 12.288 productos y manifiesto con procedencia y checksum.
- `scripts/audit_data.py`: verifica integridad y muestra cobertura y carencias.
- `scripts/fetch_data.py`: reproduce la muestra histórica fijada.
- `requirements-data.txt`: dependencias opcionales para descargarla de nuevo.
- `DATA_LICENSE.md`: atribución y condiciones de los datos.

## Comprobar los datos

Python 3.12; esta comprobación solo usa la biblioteca estándar:

```sh
python3 scripts/audit_data.py
```

Para volver a descargar el snapshot histórico:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-data.txt
python scripts/fetch_data.py
```

La muestra actual no incluye nutrientes, precios ni stock. No permite todavía
implementar el ejemplo completo. No es representativa del catálogo OFF.

## Trabajo anterior

La predicción de Green-Score y el auditor de etiquetas pertenecen a una dirección
anterior. Su código, resultados y documentos se recuperan desde la etiqueta Git
`archive/claim-audit-v1` (commit `62ff9bf`). No son resultados de Basket Optimizer.

El experimento de embeddings añadido posteriormente en el remoto se conserva en
`archive/embeddings-v1` (commit `e508342`).

# Pipeline técnico propuesto

## Producto y alcance

Entrada: productos de una cesta, cantidades comparables, preferencias y máximo K
cambios. Salida: sustituciones concretas, diferencias verificables y opción de
conservar cada producto original. Usuario: persona que organiza su compra.

MVP: tres familias con uso comparable, elegidas tras auditar cobertura; por
ejemplo bebidas de desayuno, yogures y cereales. No asumir que pertenecer a una
categoría basta para ser sustituto. País declarado no significa stock en tienda.
No incluir presupuesto hasta disponer de precios con unidad, fecha y fuente.

## 1. Catálogo y datos

Conservar el snapshot histórico sin modificarlo. Preparar un nuevo dataset
versionado que añada nutrientes por 100 g/100 ml, unidades, cantidades y evidencia
de preferencias. Mantener procedencia, valores ausentes y contexto de cada score.
No convertir desconocidos en cero. Comparar sólidos y líquidos en unidades
compatibles. La muestra actual carece de nutriments: es un bloqueo para el MVP
nutricional, no una restricción ya implementada.

Usar el score ambiental publicado en un mismo contexto, con mayor valor como
mejor indicador. No entrenar otro predictor de ese score. Un score ausente impide
recomendar ese cambio por mejora ambiental. No interpretar diferencias de score
como porcentajes de reducción de emisiones ni como kg de CO2.

## 2. Dataset de sustituciones: la supervisión propia

Crear pares producto A/producto B anotados como sustituto aceptable, no aceptable
o ambiguo, con motivo y contexto de uso. Propuesta inicial: 600–1.000 pares,
repartidos entre las familias; dos personas anotan un subconjunto compartido para
medir acuerdo y resolver discrepancias. Es un objetivo de trabajo, no datos ya
recogidos. Categorías estrechas pueden proponer pares, pero no son ground truth.

Incluir negativos difíciles: productos con ingredientes o nombres parecidos que
cumplen funciones distintas. Evitar negativos accidentales que sí sean sustitutos.
Separar train/validación/test por grupos de productos y variantes casi duplicadas
ANTES de construir los pares; ningún producto ni variante cruza particiones.
Usar solo train para minería de negativos; reservar test humano sin etiquetas débiles.

## 3. Fine-tuning del modelo de sustitución

Punto de partida candidato: paraphrase-multilingual-MiniLM-L12-v2 mediante
Sentence Transformers/PyTorch. Entrada: nombre, ingredientes y contexto de uso;
las categorías pueden filtrar candidatos, pero no deben revelar la etiqueta
artificial del entrenamiento. Encoder compartido para ambos productos.

Ajustar sus pesos con tripletas (producto, sustituto aceptable, negativo difícil)
y pérdida contrastiva o TripletLoss. El objetivo acerca sustitutos y aleja falsos
amigos. Comparar con embeddings congelados para medir qué aporta el ajuste.
Elegir margen, épocas y umbral de aceptación en validación, nunca en test.
Guardar revisión del modelo base, pesos, semilla, particiones y configuración.
No afirmar que similitud equivale a preferencia de sabor sin datos de usuarios.

## 4. Recuperación y restricciones

Precalcular embeddings del catálogo. Para cada producto, recuperar candidatos
por coseno y aplicar filtros de unidad, uso, cobertura y preferencias. Para un
catálogo pequeño basta búsqueda exacta; un índice vectorial es opcional.

Ajustar el umbral de similitud en validación para priorizar precisión. Abstenerse
si falta evidencia. Una preferencia dietética solo se satisface con evidencia
explícita suficiente; ausencia de un alérgeno en el texto no demuestra seguridad.
El MVP no certifica aptitud médica ni alergénica.

## 5. Optimización de la cesta

Variables binarias x[i,j]: elegir el candidato j para el producto i. Incluir el
original como candidato. Exigir una elección por posición y como máximo K cambios.
Bloquear sustitutos no aceptables antes de optimizar.

Objetivo inicial: maximizar mejora del score ambiental ponderada por cantidades
comparables, con penalización explícita por cambios. Su agregado se presenta como
índice experimental de la cesta, no como huella ambiental oficial.

Restricciones opcionales con datos completos: proteína total >= mínimo y azúcar o
sal <= límites elegidos. Convertir valores por 100 g/ml a cantidades de la cesta
antes de sumar; no mezclar unidades incompatibles. Usar programación entera (p.ej.
OR-Tools CP-SAT con coeficientes enteros escalados). Si las restricciones son
inviables, informar de ello y permitir al usuario cambiarlas; no relajarlas en silencio.

## 6. Resultado y explicación

Mostrar original, sustituto, datos comparables, procedencia, cambios totales y
motivo de aceptación. Texto generado por plantillas con valores calculados.
No se necesita un LLM para entrenar, recomendar, optimizar ni explicar.

## 7. Evaluación y ablaciones

Congelar test y reglas antes de medir. Tres comparaciones sobre los mismos casos:

| Sistema | Qué comprueba |
|---|---|
| Misma categoría + reglas + mejor score | Baseline sencillo |
| Encoder congelado + optimizador | Aporte de representación preentrenada |
| Encoder ajustado + optimizador | Aporte del fine-tuning propio |

Añadir comparación greedy frente al optimizador con idénticos candidatos para
separar mejora del modelo y mejora del algoritmo.

Métricas: precision@3 de sustitución con juicio humano, recall@k cuando el pool
esté suficientemente anotado, cobertura/abstenciones, cumplimiento de restricciones,
latencia y mejora del índice condicionada a sustituciones aceptadas. Evaluar
cestas reservadas, con cantidades explícitas y casos inviables. Informar resultados
por familia, tamaño del test e incertidumbre. No contar negativos no anotados como
verdad automáticamente. Completar con una prueba de aceptación con usuarios.

El entrenamiento solo aporta valor si mejora el baseline: conservar resultados
negativos. No hay resultados medidos todavía para esta nueva dirección.

## Orden de implementación

1. Auditar y ampliar catálogo; seleccionar familias con cobertura suficiente.
2. Anotar pares, fijar particiones y construir baseline.
3. Medir encoder congelado; ajustar el encoder y comparar.
4. Implementar optimizador y contrastarlo con greedy/enumeración en casos pequeños.
5. Construir demo y evaluar cestas con usuarios.

## Referencias técnicas

- Sentence Transformers, pérdidas y entrenamiento con tripletas:
  https://www.sbert.net/docs/package_reference/sentence_transformer/losses.html
- OR-Tools, optimización CP-SAT:
  https://developers.google.com/optimization/cp/cp_solver

---
id: TASK-1
title: 'Encuadrar la Luna en pantallas que no son 4:3 ni 16:9'
status: Done
assignee: []
created_date: '2026-08-03 21:17'
updated_date: '2026-08-03 23:28'
labels:
  - rendering
  - ultrawide
dependencies: []
priority: high
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
El lienzo de estrellas es 3:2 (1.500). Windows "Rellenar" cubre la pantalla y recorta lo que sobra, asi que toda pantalla mas ancha que 3:2 pierde altura. La Luna se compone 1:1 sobre el lienzo, asi que cuanto mas ancha la pantalla, mas grande se ve el disco -- hasta que se corta.

Medido sobre samples/03-midyear.tif (luna llena): el disco mide 1818 px de alto en el lienzo de 5461x3640.

  pantalla          aspecto  filas visibles  disco / alto de pantalla
  4:3   1600x1200    1.333        3640            49.9%   ok
  16:10 2880x1800    1.600        3413            53.3%   ok
  16:9  1920x1080    1.778        3072            59.2%   ok
  21:9  3440x1440    2.389        2286            79.5%   apretado
  32:9  5120x1440    3.556        1536           118.4%   SE CORTA

Direccion de la solucion: componer la Luna escalada respecto de la altura VISIBLE en vez de 1:1, para que el disco conserve una proporcion objetivo (~50%) del alto de pantalla en cualquier aspecto. El render por monitor le da un lugar natural: cada monitor ya conoce su propia geometria.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 En 21:9 y 32:9 el disco ocupa <= 55% del alto de pantalla
- [ ] #2 En 16:9 y 16:10 el resultado no cambia respecto de hoy
- [ ] #3 La Luna nunca queda cortada por el recorte, en ningun aspecto
- [ ] #4 Hay una prueba pura que fija la proporcion del disco para varios aspectos
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implementado en feat/moon-framing-wide-screens.

El disco se calcula desde la columna Diam de la efemeride (que el regex ya
capturaba y descartaba, igual que distance antes de las superlunas) y se
encoge solo lo necesario para no pasar del 70% del alto de pantalla. Nunca se
agranda.

Calibracion del campo visual del render, que la NASA no publica, medida sobre
tres muestras:
  03-midyear          Dial-A-Moon   1827 px / 1770.7" = 1.0318
  05-eclipse-visible  Dial-A-Moon   1895 px / 1836.4" = 1.0319
  07-totality         telescopico   1938 px / 1872.9" = 1.0348
Las dos de Dial-A-Moon coinciden al 0.01% y la telescopica entra dentro del
error de umbralizar un disco rojo tenue, asi que una sola constante (2093")
sirve para las dos secuencias.

Medido sobre renders reales de 5120x1440 y 3440x1440: el disco queda en 70.0%
y 70.1% del alto, contra 125.4% (cortado) y 84.2% antes.

El tope quedo en 70% y no en 55% a proposito: una superluna en perigeo llega
al 67.5% en 16:9, y bajar de ahi la encogeria hasta parecer una noche
cualquiera mientras el pie de foto sigue diciendo Supermoon. Con 70% ninguna
pantalla convencional se toca en ningun momento del ciclo.
<!-- SECTION:NOTES:END -->

---
id: TASK-1
title: 'Encuadrar la Luna en pantallas que no son 4:3 ni 16:9'
status: To Do
assignee: []
created_date: '2026-08-03 21:17'
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

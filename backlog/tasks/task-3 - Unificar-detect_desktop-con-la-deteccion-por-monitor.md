---
id: TASK-3
title: Unificar detect_desktop con la deteccion por monitor
status: To Do
assignee: []
created_date: '2026-08-03 21:17'
labels:
  - refactor
dependencies: []
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Quedan dos formas de encontrar la barra de tareas de la pantalla principal: SHAppBarMessage en detect_desktop (camino de respaldo) y rcMonitor-rcWork en monitors.py (camino por monitor). rcWork ademas es mas correcto: con la barra en autoocultar devuelve el area completa, mientras SHAppBarMessage informa el grosor igual aunque este escondida. Unificarlas cambia el comportamiento del camino de respaldo, por eso se dejo fuera del cambio original.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Una sola fuente de verdad para la barra de tareas
- [ ] #2 El cambio de comportamiento con barra en autoocultar queda documentado
<!-- AC:END -->

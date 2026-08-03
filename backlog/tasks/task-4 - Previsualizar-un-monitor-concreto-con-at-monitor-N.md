---
id: TASK-4
title: Previsualizar un monitor concreto con --at --monitor N
status: To Do
assignee: []
created_date: '2026-08-03 21:17'
labels:
  - cli
dependencies: []
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
--at usa el modelo de recorte del camino de respaldo, asi que muestra lo que se veria con un solo monitor, no lo que va a recibir cada pantalla real. Con --monitor N deberia renderizar exactamente el archivo que le tocaria a ese monitor.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 --at --monitor N usa la geometria real de ese monitor
- [ ] #2 Sin --monitor el comportamiento no cambia
<!-- AC:END -->

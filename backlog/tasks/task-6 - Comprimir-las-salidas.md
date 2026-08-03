---
id: TASK-6
title: Comprimir las salidas
status: To Do
assignee: []
created_date: '2026-08-03 21:17'
labels:
  - rendering
dependencies: []
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Los TIFF se escriben sin comprimir: 14.8 MB en la principal y 5.9 MB en la secundaria, cada hora. Sobre un campo de estrellas casi negro, LZW deberia reducirlo mucho por casi nada de CPU. Verificar antes que IDesktopWallpaper::SetWallpaper acepte el formato comprimido.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Las salidas pesan bastante menos y Windows las sigue aceptando
<!-- AC:END -->

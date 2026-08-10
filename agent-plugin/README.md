# Carousel Builder · Agent Plugin

Distribuzione compatibile con Agent Plugins della skill `carousel-builder`.

Questa build contiene solo la skill, senza server MCP. Il client scopre la skill in
`skills/carousel-builder/SKILL.md` e decide autonomamente come installarla e usarla.

La skill rileva le capacità della sessione: usa l'editor HTML locale se Python,
browser locale e ricezione degli eventi sono disponibili; negli altri casi mantiene
lo stesso flusso di revisione direttamente nella conversazione.

Il codice e la documentazione del pacchetto sono distribuiti gratuitamente con
licenza [MIT](LICENSE). I font inclusi nella skill restano soggetti alle
rispettive licenze SIL Open Font License disponibili in
[`skills/carousel-builder/assets/fonts/`](skills/carousel-builder/assets/fonts/).

La versione sorgente della skill resta nella radice del repository. Questo pacchetto è
un livello di distribuzione aggiuntivo e non modifica il flusso di installazione esistente.

## Compatibilità

Richiede un client che supporti Agent Skills e la struttura Agent Plugins 1.0.0.

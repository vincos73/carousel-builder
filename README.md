<p align="center">
  <img src="assets/icon.svg" width="80" alt="Icona Carousel Builder">
</p>

# Carousel Builder by Vincos

Skill pubblica e portabile per trasformare URL, articoli, newsletter, note e testi in caroselli editoriali verticali 4:5 per Instagram, LinkedIn e altri canali social.

## Cosa fa

- legge e sintetizza una fonte senza aggiungere informazioni estranee;
- configura un'identità visiva da sito, brand kit, descrizione manuale o profilo JSON;
- distingue tra sequenza narrativa e sequenza sezionale;
- permette di approvare profilo e testi prima della produzione grafica;
- genera una prova visuale con copertina, slide più densa e chiusura;
- produce PNG, PDF o un layout dettagliato, secondo gli strumenti disponibili;
- controlla leggibilità, contrasto, font, ritagli e corrispondenza con i testi approvati.

## Flusso

1. **Fonte**: URL, testo, note o file.
2. **Brand**: configurazione, profilo salvato oppure tema neutro.
3. **Anteprima editoriale**: profilo e testi completi da approvare.
4. **Prova visuale**: copertina, slide più densa e chiusura.
5. **Produzione**: sequenza completa soltanto dopo la seconda approvazione.
6. **Controllo finale**: verifica di tutti gli artefatti prodotti.

## Compatibilità

Questa build non presume la presenza di Canvas, di un server locale o di un editor HTML interattivo. Se l'ambiente non offre una superficie di revisione, l'approvazione avviene direttamente nella conversazione.

Per il flusso Codex con editor HTML locale, approvazioni automatiche e gestione degli artefatti, usa la [Carousel Builder Agent Edition](https://github.com/vincos73/carousel-builder-agent).

## Sistema visivo

- master 4:5: **1080×1350 px**;
- esportazione ad alta definizione: **1440×1800 px**;
- prova obbligatoria a **480×600 px**;
- adattamento tipografico automatico massimo: **8%**;
- visuale generato in copertina, con slide interne pulite per impostazione predefinita;
- font e pesi derivati dal profilo approvato, senza imporre un carattere fisso.

## Installazione

Per installare la build pubblica come skill `carousel-builder`:

```bash
git clone https://github.com/vincos73/carousel-builder.git ~/.codex/skills/carousel-builder
```

Poi invoca `$carousel-builder`.

In alternativa, scarica una release dalla sezione **Releases** e copia la cartella nella directory delle skill.

### Distribuzione Agent Plugins

Questo repository include anche un pacchetto skills-only compatibile con Agent Plugins nella cartella [`agent-plugin/`](agent-plugin/). Il pacchetto contiene `plugin.json` e la skill in `skills/carousel-builder/`; non richiede né include un server MCP.

## Modalità editoriali

- **Narrativa**: per una tesi sviluppata in passaggi dipendenti.
- **Sezionale**: per raccolte e contenuti composti da sezioni autonome.

## Feedback

Per segnalare problemi o proporre miglioramenti, apri una Issue indicando:

- tipo di fonte utilizzata;
- modalità narrativa o sezionale;
- passaggio in cui si è verificato il problema;
- risultato atteso e risultato ottenuto;
- eventuali immagini della prova, senza dati riservati.

## Licenza

Da definire.

## Autore

[Vincenzo Cosenza](https://github.com/vincos73)

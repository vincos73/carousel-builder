<p align="center">
  <img src="assets/icon.svg" width="80" alt="Icona Carousel Builder">
</p>

# Carousel Builder by Vincos

Skill adattiva per trasformare URL, articoli, newsletter, note e testi in caroselli editoriali verticali 4:5 per Instagram, LinkedIn e altri canali social.

La versione 2.0 riunisce in un solo pacchetto il flusso portabile e l'editor HTML locale. La skill verifica le capacità della sessione e sceglie automaticamente la migliore superficie di revisione disponibile, senza dipendere da Canvas.

## Cosa fa

- legge e sintetizza una fonte senza aggiungere informazioni estranee;
- configura un'identità visiva da sito, brand kit, descrizione manuale o profilo JSON;
- distingue tra sequenza narrativa e sequenza sezionale;
- permette di approvare profilo e testi prima della produzione grafica;
- offre un editor locale per correggere, riordinare, commentare e approvare le slide quando l'ambiente lo consente;
- usa la revisione conversazionale come fallback negli altri ambienti;
- genera una prova visuale con copertina, slide più densa e chiusura;
- produce PNG, PDF o un layout dettagliato, secondo gli strumenti disponibili;
- controlla leggibilità, contrasto, font, ritagli e corrispondenza con i testi approvati.

## Un'unica skill, due modalità

| Capacità della sessione | Modalità usata |
| --- | --- |
| Python 3, browser locale e ricezione degli eventi disponibili | Editor HTML locale con invio automatico di correzioni e approvazioni |
| Una o più capacità mancanti | Revisione direttamente nella conversazione |

La scelta dipende dalle capacità effettivamente rilevate, non dal nome del prodotto. In ChatGPT Web, Claude o altri client privi di accesso al browser locale, la skill continua a funzionare con il fallback conversazionale. In un ambiente agentico compatibile, come Codex con gli strumenti necessari, può aprire l'editor locale.

## Flusso

1. **Fonte**: URL, testo, note o file.
2. **Brand**: configurazione, profilo salvato oppure tema neutro.
3. **Anteprima editoriale**: profilo e testi completi da revisionare e approvare.
4. **Prova visuale**: copertina, slide più densa e chiusura.
5. **Produzione**: sequenza completa soltanto dopo la seconda approvazione.
6. **Controllo finale**: verifica di tutti gli artefatti prodotti.

## Sistema visivo

- master 4:5: **1080×1350 px**;
- esportazione ad alta definizione: **1440×1800 px**;
- prova obbligatoria a **480×600 px**;
- adattamento tipografico automatico massimo: **8%**;
- visuale generato in copertina, con slide interne pulite per impostazione predefinita;
- numerazione progressiva nell'angolo superiore destro per le sequenze narrative;
- font e pesi derivati dal profilo approvato, senza imporre un carattere fisso.

## Installazione

Per installare la skill `carousel-builder`:

```bash
git clone https://github.com/vincos73/carousel-builder.git ~/.codex/skills/carousel-builder
```

Poi invoca `$carousel-builder`.

In alternativa, scarica una release dalla sezione **Releases** e copia la cartella nella directory delle skill del client.

### Distribuzione Agent Plugins

Il repository include anche un pacchetto skills-only compatibile con Agent Plugins nella cartella [`agent-plugin/`](agent-plugin/). Il pacchetto contiene `plugin.json` e la skill in `skills/carousel-builder/`; non richiede né include un server MCP.

## Modalità editoriali

- **Narrativa**: per una tesi sviluppata in passaggi dipendenti.
- **Sezionale**: per raccolte e contenuti composti da sezioni autonome.

## Evoluzione dalla Agent Edition

Le funzioni sperimentate nella precedente Agent Edition sono ora incluse nella versione pubblica 2.0. Il vecchio repository separato non è più necessario per l'installazione e resta soltanto come backup storico privato.

## Feedback

Per segnalare problemi o proporre miglioramenti, apri una Issue indicando:

- tipo di fonte utilizzata;
- modalità narrativa o sezionale;
- modalità di revisione usata;
- passaggio in cui si è verificato il problema;
- risultato atteso e risultato ottenuto;
- eventuali immagini della prova, senza dati riservati.

## Licenza

Distribuita gratuitamente con licenza [MIT](LICENSE). Puoi usare, modificare e
ridistribuire la skill, mantenendo l'avviso di copyright e il testo della
licenza.

## Autore

[Vincenzo Cosenza](https://github.com/vincos73)

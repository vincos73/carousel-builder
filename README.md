# Carousel Builder by Vincos

Carousel Builder è una skill adattiva per trasformare URL, articoli, newsletter, note e testi in caroselli editoriali verticali 4:5 per Instagram, LinkedIn e altri canali social.

Può essere usata con ChatGPT e Claude (versioni web), ma dà il meglio quando viene usata con le versioni desktop. In particolare se usata con ChatGPT Desktop permette una revisione visiva delle slide del carosello attraverso un editor html.

<img width="1256" height="701" alt="carousel-builder-screenshot" src="https://github.com/user-attachments/assets/1e4de6de-2960-405d-881c-21d6d14b943c" />

## Inizia da qui

Puoi scaricare subito il pacchetto in formato ZIP:

[**Scarica Carousel Builder**](https://github.com/vincos73/carousel-builder/releases/latest/download/carousel-builder.zip)

Non serve conoscere GitHub o usare il terminale per iniziare.

1. Scarica il file ZIP dal link qui sopra.
2. Se il tuo strumento permette di caricare una skill, carica direttamente il file ZIP. Se chiede una cartella, scompatta il file e seleziona la cartella `carousel-builder`.
3. Dopo l'installazione, invoca la skill con `$carousel-builder` e incolla un URL, un testo o le tue note.

Il pacchetto contiene soltanto la skill, in una cartella già chiamata `carousel-builder` come richiesto da alcuni client. Se preferisci l'ultimo stato del repository invece dell'ultima versione pubblicata, puoi sempre scaricare [l'archivio del ramo `main`](https://github.com/vincos73/carousel-builder/archive/refs/heads/main.zip), che però include anche i file di sviluppo e si estrae come `carousel-builder-main`.

Se usi ChatGPT Desktop e preferisci installarla dalla riga di comando, trovi il comando nella sezione [Installazione locale](#installazione-locale).

## Cosa fa

- legge e sintetizza una fonte senza aggiungere informazioni estranee;
- configura un'identità visiva da sito, brand kit, descrizione manuale o profilo JSON;
- distingue tra sequenza narrativa e sequenza sezionale;
- permette di approvare profilo e testi prima della produzione grafica;
- offre un editor locale per correggere, riordinare, commentare e approvare le slide quando l'ambiente lo consente;
- usa la revisione conversazionale come fallback negli altri ambienti;
- produce PNG, PDF o un layout dettagliato, secondo gli strumenti disponibili;
- controlla leggibilità, contrasto, font, ritagli e corrispondenza con i testi approvati.

## Un'unica skill, due modalità

La skill si adatta all'ambiente di lavoro dell'utente: in ChatGPT Web, Claude o altri client privi di accesso al browser locale, la skill funziona in modalità conversazionale. 
In un ambiente agentivo compatibile, come ChatGPT Desktop può aprire l'editor locale per dar modo di fare modifiche mirate.

| Capacità della sessione | Modalità usata |
| --- | --- |
| Python 3, apertura di un indirizzo locale nel browser e ricezione degli eventi del server: tutte e tre disponibili | Editor HTML locale con invio automatico di correzioni e approvazioni |
| Anche una sola delle tre non è disponibile | Revisione direttamente nella conversazione |


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

## Installazione locale

Questa procedura serve soltanto per installare la skill nella directory locale di Codex. Apri il terminale e scrivi:

```bash
curl -L https://github.com/vincos73/carousel-builder/releases/latest/download/carousel-builder.zip -o carousel-builder.zip
unzip -q carousel-builder.zip
mkdir -p ~/.codex/skills
cp -R carousel-builder ~/.codex/skills/
```

Poi riapri o aggiorna Codex e invoca `$carousel-builder`.

### Distribuzione Agent Plugins

Il repository include anche un pacchetto skills-only compatibile con Agent Plugins nella cartella [`agent-plugin/`](agent-plugin/). Il pacchetto contiene `plugin.json` e la skill in `skills/carousel-builder/`; non richiede né include un server MCP.

Il contenuto di `agent-plugin/skills/carousel-builder/` è una copia esatta della skill nella radice del repository. Ogni modifica va replicata in entrambe le posizioni: la CI confronta le due copie e fallisce se divergono.

## Sviluppo

I due script del percorso `local-editor` sono coperti da test con la sola libreria standard, senza dipendenze da installare:

```bash
python3 -m unittest discover -s tests -t tests -v
```

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

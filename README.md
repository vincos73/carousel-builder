# Carousel Builder by Vincos

Carousel Builder è una skill adattiva per trasformare URL, articoli, newsletter, testi in caroselli editoriali verticali 4:5 per Instagram, LinkedIn e altri canali social (formato .pdf e .png).

Può essere usata con ChatGPT e Claude (versioni web), ma dà il meglio quando viene usata con le versioni desktop. In particolare se usata con ChatGPT Desktop e Claude Code permette una revisione visiva delle slide del carosello attraverso un editor html.

Se usi Claude tieni presente che Anthropic non dispone di un modello nativo per la generazione di immagini per cui ti restituirà delle slide molto scarne.

<img width="1557" height="845" alt="carousel-builder-screen" src="https://github.com/user-attachments/assets/cb3a3ead-513f-43b3-80c4-75da692b5857" />


## Inizia da qui

Puoi scaricare subito il pacchetto ZIP versionato:

[**Apri l'ultima release di Carousel Builder**](https://github.com/vincos73/carousel-builder/releases/latest)

Non serve conoscere GitHub o usare il terminale per iniziare.

1. Scarica il file `carousel-builder-vX.Y.Z.zip` dall'ultima release.
2. Se il tuo strumento IA permette di caricare una skill, carica direttamente il file ZIP. Se chiede una cartella, scompatta il file e seleziona la cartella `carousel-builder`.
3. Dopo l'installazione, invoca la skill con `$carousel-builder` o `/carousel-builder` e incolla un URL, un testo o le tue note.

Il pacchetto contiene soltanto la skill, in una cartella già chiamata `carousel-builder` come richiesto da alcuni client. Se preferisci l'ultimo stato del repository invece dell'ultima versione pubblicata, puoi sempre scaricare [l'archivio del ramo `main`](https://github.com/vincos73/carousel-builder/archive/refs/heads/main.zip), che però include anche i file di sviluppo e si estrae come `carousel-builder-main`.

Se preferisci installarla dalla riga di comando, trovi il comando nella sezione [Installazione locale](#installazione-locale).

## Cosa fa

- legge e sintetizza una fonte senza aggiungere informazioni estranee;
- configura un'identità visiva da sito, brand kit, descrizione manuale o profilo JSON;
- distingue tra sequenza narrativa e sequenza sezionale (titolo e corpo);
- permette di approvare profilo e testi prima della produzione grafica;
- propone un solo sistema visivo consigliato, con un confronto opzionale e Geometrico come scelta avanzata;
- permette di scegliere subito una copertina tipografica o con visuale, generando l'eventuale immagine soltanto dopo l'approvazione dei testi;
- offre un editor locale per correggere, riordinare, commentare e approvare le slide quando l'ambiente lo consente (con ChatGPT desktop e Claude Code);
- usa la revisione conversazionale come fallback negli altri ambienti;
- produce PNG, PDF o un layout dettagliato, secondo gli strumenti messi a disposizione dall'ambiente di lavoro;
- segnala leggibilità, contrasto, font, ritagli e densità come avvisi consultivi, lasciando all'utente la decisione finale;
- nel percorso locale lega approvazioni, export e QA a revisione, fingerprint e digest degli artefatti, genera automaticamente il report tecnico e riprende dalle ricevute durevoli dopo un'interruzione.

## Un'unica skill, due modalità

La skill si adatta all'ambiente di lavoro dell'utente: in ChatGPT Web, Claude o altri client privi di accesso al browser locale, la skill funziona in modalità conversazionale, cioè fa domande all'utente per aiutarlo a configurare il carosello. 
In un ambiente agentivo compatibile, come ChatGPT Desktop e Claude Code, può aprire l'editor locale per dar modo di fare modifiche mirate.

| Capacità della sessione | Modalità usata |
| --- | --- |
| ChatGPT/Codex Desktop e Claude Code con Python 3.10+ e browser use disponibile | Editor HTML locale con invio automatico di correzioni e approvazioni |
| Chatbot che non hanno disponibilità di questi strumenti | Revisione attraverso conversazione testuale |


## Flusso

1. **Fonte**: tu gli dai un URL, un testo o un file e gli chiedi di creare un carosello
2. **Brand**: la skill ti chiederà quali sono le caratteristiche del tuo brand (puoi anche caricare file di brand identity)
3. **Anteprima editoriale**: si aprirà un editor che ti farà vedere e modificare il carosello.
4. **Produzione**: nel caso normale premi `Genera`; i checkpoint tecnici restano tracciati internamente e gli output vengono consegnati dopo i controlli di integrità

## Modalità editoriali

Due le modalità di sviluppo del carosello:

- **Narrativa**: il testo viene sviluppato in una sequenza chiara (ideale per un argomento)
- **Sezionale**: il testo viene composto in slide autonome (ideale per raccolte di contenuti)

## Sistemi editoriali

Tre i modelli di carosello disponibili. Il percorso normale ne consiglia uno; l'utente può confrontare una sola alternativa e aprire Geometrico come opzione avanzata:

- **Editoriale**: minimal, caratterizzato da una cornice continua 
- **Geometrico**: estroso, caratterizzato da forme circolari colorate
- **Frame**: espressivo e ordinato, con un foglio chiaro incastonato tra fondo scuro e accento del brand
  
## Sistema visivo

- master 4:5: **1080×1350 px**;
- esportazione ad alta definizione: **1440×1800 px**;
- prova obbligatoria a **480×600 px**;
- adattamento tipografico automatico massimo: **8%**;
- immagine opzionale generata dopo l'approvazione dei testi (solo negli ambienti che possono creare immagini), collocata in una colonna verticale a destra con il titolo a sinistra e senza sovrapposizioni;
- numerazione progressiva nell'angolo superiore destro; nella cover con visuale resta dentro la colonna testuale;
- font e pesi derivati dal profilo approvato, senza imporre un carattere fisso.

## Installazione locale

Questa procedura serve soltanto per installare la skill nella directory locale di Codex. Apri il terminale e scrivi:

```bash
unzip -q carousel-builder-vX.Y.Z.zip
mkdir -p ~/.codex/skills
cp -R carousel-builder ~/.codex/skills/
```

Poi riapri o aggiorna Codex e invoca `$carousel-builder`.

### Distribuzione Agent Plugins

Il repository include anche un pacchetto skills-only compatibile con Agent Plugins nella cartella [`agent-plugin/`](agent-plugin/). Il pacchetto contiene `plugin.json` e la skill in `skills/carousel-builder/`; non richiede né include un server MCP.

Il contenuto di `agent-plugin/skills/carousel-builder/` è una copia esatta della skill nella radice del repository. Ogni modifica va replicata in entrambe le posizioni: la CI confronta le due copie e fallisce se divergono.

## Diagnosi del workflow locale

La versione 2.10 mantiene un controllo JSON unico e read-only. Valida manifest, proof e sessione, segnala feedback pendente e indica il prossimo passo sicuro senza modificare lo stato:

```bash
python3 scripts/carousel_status.py /percorso/manifest.json \
  --session-dir /percorso/sessione
```

Il campo `next_action` restituisce la fase di revisione, il comando sicuro o gli output attesi dall'export. Il percorso normale usa `process_review.py` per applicare e avanzare il solo checkpoint approvato, `attach_cover_asset.py` per collegare una cover dopo i testi e `finalize_delivery.py` per i due gate finali e il report QA automatico. Senza `--session-dir` lo status esegue una validazione statica e dichiara esplicitamente che lo stato del feedback non è verificabile.

## Sviluppo

Gli entrypoint del percorso `local-editor` sono coperti da test automatici. Il contratto manifest e gli strumenti Python usano la sola libreria standard; l'esportatore PDF usa le librerie Node già disponibili nell'ambiente. La CI esegue anche il percorso completo con server e Chromium reali, usando dipendenze di test bloccate nel lockfile. L'export può pubblicare un risultato JSON con digest degli artefatti, poi legato alle ricevute di stato e al report QA:

```bash
python3 -m unittest discover -s tests -t tests -v
node --test tests/test_export_review_pdf.cjs
npm ci --ignore-scripts && node --test tests/test_export_review_pdf_e2e.cjs
```

## Feedback

Per segnalare problemi o proporre miglioramenti, apri una Issue indicando:

- tipo di fonte utilizzata;
- modalità narrativa o sezionale;
- modalità di revisione usata;
- passaggio in cui si è verificato il problema;
- risultato atteso e risultato ottenuto;
- eventuali immagini della prova, senza dati riservati.

## Licenza

Il codice e la documentazione sono distribuiti gratuitamente con licenza
[MIT](LICENSE). Puoi usarli, modificarli e ridistribuirli mantenendo l'avviso
di copyright e il testo della licenza.

Il profilo neutro usa Arial e Times New Roman già installati nel sistema; la
skill non ridistribuisce file di font.

## Autore

[Vincenzo Cosenza](https://github.com/vincos73)

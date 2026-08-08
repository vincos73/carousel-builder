# Revisione editoriale visuale

Il modello `/api/model` espone `visual_proofs` come oggetto calcolato dal server con `selected_style_system`, identità condivisa e tre opzioni. Non persistere questo oggetto nel manifest: inviare la scelta come `visual_style_system` e applicarla con `scripts/apply_review.py`.

Usare questa modalità soltanto quando Python 3 e un browser locale sono già disponibili. Non installare dipendenze. Il browser non deve scrivere direttamente nel manifest: deve inviare un batch strutturato che l'agente applica e controlla.

## Preparazione

1. Salvare il manifest del carosello in una cartella di lavoro accessibile all'utente.
2. Scegliere una cartella di sessione dedicata, esterna alla cartella della skill.
3. Avviare il server con percorsi assoluti:

```text
python3 <skill>/scripts/review_server.py <manifest.json> --session-dir <session-dir>
```

4. Leggere dalla prima riga JSON l'indirizzo locale e aprirlo nel browser disponibile.
5. Mantenere attivo il processo mentre l'utente revisiona e restare in ascolto del suo output. Non concludere il turno subito dopo aver aperto l'editor e non chiedere all'utente di tornare in chat per scrivere «fatto».
6. Attendere l'evento del server con il meccanismo di ripresa del processo disponibile nella sessione. Usare attese non superiori a 50 secondi per volta, così da poter inviare un aggiornamento conciso almeno ogni 60 secondi. Ripetere l'attesa finché arriva un batch, l'utente interrompe il lavoro o il task non può più restare attivo.
7. Se la sessione non consente un'attesa attiva sufficientemente lunga, dichiarare il limite prima di consegnare l'editor e usare come fallback la ripresa manuale in chat.

Il server deve restare vincolato a `127.0.0.1`, usare un token casuale e servire soltanto gli asset inclusi e il modello editoriale ricavato dal manifest.

## Interazioni dell'MVP

L'editor consente di:

- modificare copertina, titoli sezionali, corpi e chiusura;
- spostare le slide interne in alto o in basso;
- eliminare una slide interna;
- commentare una selezione testuale;
- aggiungere un commento all'intera slide;
- aggiungere una nota generale;
- inviare correzioni oppure richiedere esplicitamente l'approvazione.

Nella card di copertina e nella conferma di approvazione, chiarire che la copertina finale non è ancora inclusa: dopo l'approvazione dei testi sarà mostrata in una prova visuale separata con immagine generata, immagine fornita o composizione tipografica.

Non consentire di eliminare copertina o chiusura. Non interpretare grassetto, corsivo o altre formattazioni come enfasi semantiche.

## Ricezione e applicazione

Quando il server segnala un batch, riprendere automaticamente il lavoro e leggere `<session-dir>/feedback.json`. Prima di applicarlo controllare che:

- `base_revision` corrisponda alla revisione corrente del manifest;
- tutti gli ID delle slide appartengano al manifest corrente;
- resti almeno una slide interna;
- il batch non superi i limiti dichiarati dal server.

Applicare le modifiche dirette con:

```text
python3 <skill>/scripts/apply_review.py <manifest.json> <session-dir>/feedback.json --session-dir <session-dir>
```

Lo script deve aggiornare soltanto i campi editoriali consentiti, preservare un backup nella cartella di sessione, incrementare `revision` quando cambia il testo o l'ordine e non modificare automaticamente `workflow_state`.

Lo script riallinea inoltre i riferimenti derivati dai testi:

- rimuove dai campi `*_serif` e `*_accent` le frasi che non compaiono più nel testo aggiornato e le elenca in `emphasis_dropped`;
- ricostruisce `accessibility.reading_order` secondo la sequenza risultante;
- elimina da `proof.slide_ids` gli ID delle slide non più presenti e li elenca in `proof_slide_ids_pruned`.

Leggere sempre `warnings`, `stale_alt_text` e `stale_transcript` nell'output. Lo script non riscrive i testi descrittivi: gli `alt_text` delle slide modificate e la trascrizione di accessibilità restano invariati e vanno rigenerati dall'agente prima della produzione. Se il batch invalida una prova già approvata, lo script lo segnala senza modificare `proof.approved`.

L'editor carica separatamente `display` per copertina e titoli e `body` per testi e metadati. Nei profili legacy usa `sans` per entrambi. Espone inoltre `cover_subtitle` come campo opzionale: se presente, l'anteprima lo rende nel secondo carattere corsivo; la stessa regola vale per tutte le enfasi serif.

Esaminare poi `comments` e `overall_note`. I commenti sono richieste da interpretare, non modifiche già effettuate. Applicare le correzioni necessarie al manifest, ripetere i controlli editoriali e aggiornare la revisione se occorre.

Se `action` è `approve`, trattarla come richiesta esplicita di approvazione. Impostare `workflow_state: testi_approvati` soltanto dopo aver risolto i commenti e superato i controlli. In caso contrario mantenere `bozza`.

## Ripresa e chiusura

Il browser conserva una bozza locale finché il batch non viene inviato. Il server conserva l'ultimo batch nella cartella di sessione. Se il processo si interrompe, riavviarlo con gli stessi manifest e cartella di sessione.

Dopo aver applicato il batch, lo script registra l'esito in `session-state.json`; l'editor rileva il nuovo stato e ricarica il manifest aggiornato. L'editor confronta anche la revisione del manifest con quella che sta mostrando: quando l'agente incrementa `revision` risolvendo i commenti, la pagina si aggiorna da sola se non ci sono modifiche locali in sospeso, altrimenti blocca l'invio e propone il ricarico. Non chiedere all'utente di aggiornare la pagina a mano. Chiudere il processo del server quando la revisione è terminata o l'utente interrompe il lavoro.

Se il server, il browser o l'applicazione del batch falliscono, non modificare lo stato del workflow. Offrire la revisione conversazionale come fallback dichiarato.

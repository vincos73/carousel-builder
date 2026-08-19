# Revisione editoriale visuale

`/api/session` calcola `visual_proofs` con sistema consigliato, alternativa, opzione avanzata e identità condivisa. L'editor mostra prima il consiglio. Non persistere l'oggetto: inviare la scelta come `visual_style_system`.

Usare questa modalità soltanto quando Python 3.10 o successivo e un browser locale sono già disponibili. Non installare dipendenze. Il browser non deve scrivere direttamente nel manifest: deve inviare un batch strutturato che l'agente applica e controlla.

## Preparazione

1. Salvare il manifest in una cartella accessibile. Registrare `cover_mode`, ma non generare o collegare un nuovo asset di copertina durante `bozza`.
2. Scegliere una cartella di sessione dedicata, esterna alla cartella della skill.
3. Avviare il server con percorsi assoluti:

```text
python3 <skill>/scripts/review_server.py <manifest.json> --session-dir <session-dir>
```

4. Assegnare una sola superficie browser alla sessione prima di aprire l'indirizzo della prima riga JSON. Preferire e riusare la scheda del browser interno quando disponibile; usare Chrome o un launcher di sistema soltanto se l'utente lo richiede o se il browser interno non è utilizzabile. Non aprire lo stesso editor in entrambe le superfici. Con capacità locali, l'apertura dell'editor è obbligatoria. Prima di consegnarlo, controllare copertina e card nel sistema consigliato a 480 px; controllare l'alternativa solo se verrà mostrata. Correggere soglie o overflow finché la proposta visibile è pulita.
5. Mantenere attivo il processo e ascoltarlo in ogni checkpoint dell'editor: testi, prova visuale e nuove prove. Non concludere il turno dopo l'apertura né chiedere di scrivere «fatto». Appena arriva un batch, confermarne la ricezione in chat prima di elaborarlo; l'utente non deve interpretare il silenzio come un blocco.
   La ricezione è una fase obbligatoria del workflow, non un controllo successivo: subito dopo aver aperto la scheda, attendere sul processo del server per intervalli non superiori a 50 secondi e ripetere l'attesa finché arriva l'evento o l'utente interrompe. Non inviare una risposta finale mentre l'editor attende un'azione. Se l'ambiente restituisce un identificativo di processo o sessione, riutilizzare esattamente quello per tutte le attese; non affidarsi al solo polling del browser.
6. Attendere al massimo 50 secondi per volta. Senza output, leggere `session-state.json`: se `last_feedback_id` differisce da `applied_feedback_id`, usare `last_action` e `last_feedback_path` come segnale durevole. Per stati legacy usare `feedback.json`. Ripetere finché arriva un batch o l'utente interrompe.
7. Considerare l'output del processo una notifica immediata e `session-state.json` la fonte durevole per il recupero. Se la sessione non consente un'attesa attiva sufficientemente lunga né la lettura dello stato, dichiarare il limite prima di consegnare l'editor e usare come fallback la ripresa manuale in chat.

Il server deve restare vincolato a `127.0.0.1`, usare un token casuale e servire soltanto gli asset inclusi e il modello editoriale ricavato dal manifest.

`/api/session` espone `render_fingerprint` e stato durevole del feedback sotto lock. Il fingerprint lega snapshot, contratto di produzione/output, bundle e asset, ma non il checkpoint né l'elenco dichiarativo dei sistemi supportati. Su `approve`, il browser invia fingerprint e `base_workflow_state`; il server deriva lo stage e calcola il candidato. Lo stato base impedisce comunque a un click stale di attraversare un checkpoint. `/api/status` espone stato e checkpoint anche senza nuova revisione.

Nel checkpoint visuale `proof.required_slide_ids` contiene copertina, card più densa e chiusura. L'editor lega il campione visto a revisione, checkpoint, fingerprint e sistema, poi invia ID, verifica stile e major Chromium. Inviare prima ogni correzione locale. Solo Chromium può firmare il proof esportabile.

`?render=production` carica il manifest approvato, ignora bozze e pubblica `approved-preview-dom-v2`. L'esportatore acquisisce ogni `.slide-preview` e rifiuta geometrie diverse dall'anteprima pulita.

## Interazioni dell'editor

L'interfaccia rende disponibili modifica, riordino, commenti, enfasi tipografiche, scelta progressiva del sistema visivo, modalità del logo e intenzione della copertina. `Con visuale` non blocca l'approvazione editoriale: nello stato `testi_approvati` segnala che l'asset va prodotto e collegato prima della prova. Nel percorso normale affidarsi ai controlli e ai messaggi dell'editor. Leggere [editor-capabilities.md](editor-capabilities.md) soltanto se l'utente chiede istruzioni su questi comandi o se occorre diagnosticare un blocco dell'interfaccia.

L'editor mostra tre passaggi persistenti: profilo e testi, prova visiva, produzione. Il consenso sui testi e quello sulla prova visiva devono avere etichette diverse. Il percorso combinato è ammesso soltanto quando viene annunciato prima del click come consenso unico su testi e grafica. Nello stato `testi_approvati`, mostrare per default la galleria della prova; riaprire i controlli soltanto dopo l'azione esplicita `Modifica contenuti o grafica`, spiegando quali checkpoint verranno invalidati.

## Ricezione e applicazione

Quando il server segnala un batch, riprendere automaticamente il lavoro e leggere `archive_path`, oppure `last_feedback_path` dallo stato quando la notifica non è arrivata. Usare `<session-dir>/feedback.json` soltanto come alias compatibile con le sessioni precedenti. Prima di applicarlo controllare che:

- `session-state.json` associ la cartella di sessione allo stesso manifest richiesto;
- `base_revision` corrisponda alla revisione corrente del manifest;
- tutti gli ID delle slide appartengano al manifest corrente;
- resti almeno una slide interna;
- il batch non superi i limiti dichiarati dal server.

Elaborare il batch normale con:

```text
python3 <skill>/scripts/process_review.py <manifest.json> <feedback-path> --session-dir <session-dir>
```

`process_review.py` invoca `apply_review.py` e legge lo status. `approve` avanza solo il checkpoint valido, mai `rendering`; con `approval_scope: profile_text_and_visual` avanza in sequenza i due checkpoint iniziali e conserva due ricevute. Il server accetta questo scope soltanto da `bozza`, con cover tipografica, renderer canonico, campione completo in Chromium, stile supportato e nessuna nota, commento o warning. `feedback` non avanza. Accetta l'alias `feedback.json` o un batch della sessione in `feedback-batches/`; alias e batch append-only devono coincidere.

`apply_review.py` limita i campi, crea backup e incrementa `revision` quando serve. Copy, ordine, profilo o richieste ambigue riaprono `bozza`; sistema, logo, cover o enfasi mantengono `testi_approvati`. Il visual proof ricontrolla il fingerprint e lega `proof.approved`.

Dopo l'approvazione dei testi, collegare una cover richiesta con:

```text
python3 <skill>/scripts/attach_cover_asset.py <manifest.json> <image> \
  --session-dir <session-dir> --expected-revision N --mode generated \
  --alt-text "Descrizione del visuale"
```

Usare `--mode provided` per un asset dell'utente e aggiungere posizione, concetti, metafora o prompt quando disponibili. Lo script copia in modo sicuro l'asset, registra e applica un batch durevole, incrementa la revisione e lascia lo stato in `testi_approvati`. Una revisione stale viene rifiutata prima della copia.

Lo script riallinea inoltre i riferimenti derivati dai testi:

- rimuove dai campi `*_bold`, `*_italic`, `*_serif` legacy, `*_underline` e `*_accent` le locuzioni che non compaiono più nel testo aggiornato e le elenca in `emphasis_dropped`;
- ricostruisce `accessibility.reading_order` secondo la sequenza risultante;
- ricostruisce `proof.slide_ids` come copertina, card più densa e chiusura opzionale, elencando in `proof_slide_ids_pruned` gli ID non più inclusi.

Leggere `warnings`, `stale_alt_text` e `stale_transcript`. Rigenerare i testi descrittivi stale. Le correzioni invalidano proof e browser quando necessario. Un `approve` visuale non include modifiche editoriali; un feedback vuoto non riapre checkpoint.

L'editor carica separatamente `display` per copertina e titoli e `body` per testi e metadati. Nei profili legacy usa `sans` per entrambi. Risolve `emphasis_italic` secondo [brand-profile.md](brand-profile.md), ne mostra il nome nell'interfaccia e non sintetizza un corsivo mancante. Espone inoltre `cover_subtitle` come campo opzionale e lo rende nello stesso ruolo corsivo.

Per l'anteprima dei logo servire soltanto asset raster autorizzati. Quando il master dichiarato è SVG e nella stessa cartella esiste un PNG omonimo, usare il PNG come derivato di anteprima e indicarlo nel pannello Brand. Non servire SVG non sanitizzati e non sostituire il master usato nella produzione finale.

Esaminare poi `comments` e `overall_note`. I commenti sono richieste da interpretare, non modifiche già effettuate. Applicare le correzioni necessarie al manifest, ripetere i controlli editoriali e aggiornare la revisione se occorre.

Se `action` è `approve`, trattarla come richiesta esplicita ma lasciare che `process_review.py` esegua gli avanzamenti attestati coperti dallo scope ricevuto. Se restituisce `approval_blocked`, leggere lo status incluso, correggere il gate e mantenere il checkpoint. Non modificare stato o ricevute a mano e non richiedere un nuovo consenso quando il medesimo batch può essere rielaborato dopo una correzione tecnica non visuale.

## Ripresa e chiusura

Dopo l'applicazione il server registra l'esito in `session-state.json` e l'editor ricarica la base aggiornata senza refresh manuale. Chiudere il server quando la revisione termina o l'utente interrompe il lavoro. Se una risposta si perde, il processo si interrompe o compare un conflitto fra basi o schede, leggere [review-recovery.md](review-recovery.md) prima di agire.

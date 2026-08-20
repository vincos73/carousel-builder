# Revisione editoriale visuale

`/api/session` calcola `visual_proofs` con sistema consigliato, alternativa, opzione avanzata e identità condivisa. L'editor mostra prima il consiglio. Non persistere l'oggetto: inviare la scelta come `visual_style_system`.

Usare questa modalità soltanto quando Python 3.10 o successivo e un browser locale sono già disponibili. Non installare dipendenze. Il browser non deve scrivere direttamente nel manifest: deve inviare un batch strutturato che l'agente applica e controlla.

## Preparazione

1. Salvare il manifest in una cartella accessibile. Registrare `cover_mode`, ma non generare o collegare un nuovo asset di copertina durante `bozza`.
2. Scegliere una cartella di sessione dedicata, esterna alla cartella della skill.
3. Avviare il server con percorsi assoluti:

```text
python3 <skill>/scripts/review_server.py <manifest.json> --session-dir <session-dir> [--return-thread-id <thread-id>]
```

4. Usare una sola superficie: preferire e riusare il browser interno; usare Chrome solo su richiesta o se quello interno non funziona. Con capacità locali, l'apertura dell'editor è obbligatoria. Controllare la proposta a 480 px prima di mostrarla.
5. Mantenere il processo in ascolto in ogni checkpoint dell'editor. Non concludere il turno dopo l'apertura né chiedere «fatto». Confermare subito in chat ogni batch ricevuto. Con `--return-thread-id`, mostrare `Torna alla chat` dopo l'invio e negli stati successivi, usando solo `codex://threads/<thread-id>`. A ogni turno acquisire o riusare la tab e chiamare `markHandoff()` prima del lavoro e prima di una possibile fine; reclamare una tab visibile con binding stale. Il ritorno avviene solo dopo il click dell'utente, mai automaticamente.
   Dopo l'apertura attendere sul processo per intervalli fino a 50 secondi, riusando il suo identificativo. Ripetere finché arriva l'evento o l'utente interrompe; non inviare una risposta finale durante l'attesa.
6. Attendere al massimo 50 secondi per volta. Senza output, leggere `session-state.json`: se `last_feedback_id` differisce da `applied_feedback_id`, usare `last_action` e `last_feedback_path` come segnale durevole. Per stati legacy usare `feedback.json`. Ripetere finché arriva un batch o l'utente interrompe.
7. Usare l'output come notifica e `session-state.json` come fonte durevole. Se attesa e lettura dello stato non sono possibili, dichiararlo e usare la ripresa manuale in chat.

Il server deve restare vincolato a `127.0.0.1`, usare un token casuale e servire soltanto gli asset inclusi e il modello editoriale ricavato dal manifest.

`/api/session` espone `render_fingerprint` e feedback durevole sotto lock. Il fingerprint lega snapshot, produzione, bundle e asset. Su `approve`, il browser invia fingerprint e `base_workflow_state`; il server deriva lo stage. `/api/status` espone stato e checkpoint.

Nel checkpoint visuale `proof.required_slide_ids` contiene copertina, card più densa e chiusura. L'editor lega revisione, checkpoint, fingerprint e sistema, poi invia gli ID canonici e la major Chromium. Il campo legacy `proof.style_system_verified` è soltanto diagnostico e può restare `false`: la decisione visuale appartiene all'utente. Inviare prima ogni correzione locale. Solo Chromium può firmare il contratto tecnico esportabile.

`?render=production` carica il manifest approvato, ignora bozze e pubblica `approved-preview-dom-v2`. L'esportatore acquisisce ogni `.slide-preview` e rifiuta geometrie diverse dall'anteprima pulita.

## Interazioni dell'editor

L'interfaccia rende disponibili modifica, riordino, commenti, enfasi tipografiche, scelta progressiva del sistema visivo, modalità del logo e intenzione della copertina. `Con visuale` non blocca l'approvazione editoriale: nello stato `testi_approvati` segnala che l'asset va prodotto e collegato prima della prova. Nel percorso normale affidarsi ai controlli e ai messaggi dell'editor. Leggere [editor-capabilities.md](editor-capabilities.md) soltanto se l'utente chiede istruzioni su questi comandi o se occorre diagnosticare un blocco dell'interfaccia.

L'editor mostra tre passaggi persistenti: profilo e testi, prova visiva, produzione. Nel percorso normale espone una sola azione primaria, `Genera`, che registra la decisione dell'utente e copre i due checkpoint iniziali quando il contratto tecnico lo consente. `Invia correzioni` compare solo dopo l'aggiunta di commenti oppure quando si modifica un contenuto già approvato e serve un nuovo passaggio dell'agente. Nello stato `testi_approvati`, mostrare per default la galleria della prova; riaprire i controlli soltanto dopo l'azione esplicita `Modifica contenuti o grafica`, spiegando quali checkpoint verranno invalidati.

## Ricezione e applicazione

Quando il server segnala un batch, riprendere automaticamente il lavoro e leggere `archive_path`, oppure `last_feedback_path` dallo stato quando la notifica non è arrivata. Usare `<session-dir>/feedback.json` soltanto come alias compatibile con le sessioni precedenti. Prima di applicarlo controllare che:

- `session-state.json` associ la cartella di sessione allo stesso manifest richiesto;
- `base_revision` corrisponda alla revisione corrente del manifest;
- tutti gli ID delle slide appartengano al manifest corrente;
- resti almeno una slide interna;
- il batch rispetti dimensioni, numero di slide e limiti strutturali dichiarati dal server.

Elaborare il batch normale con:

```text
python3 <skill>/scripts/process_review.py <manifest.json> <feedback-path> --session-dir <session-dir>
```

`process_review.py` applica il batch e legge lo status. `approve` avanza solo i checkpoint coperti, mai `rendering`; lo scope combinato conserva due ricevute ed è ammesso solo da `bozza` con cover tipografica, renderer canonico, Chromium, stile supportato e nessuna nota o commento. Gli avvisi non lo bloccano; `feedback` non avanza. Dopo `prova_visuale_approvata`, confermare in chat e continuare subito con `next_action`, export, QA e consegna.

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

L'editor carica separatamente `display` per copertina e titoli e `body` per testi e metadati. Nei profili legacy usa `sans` per entrambi. Risolve `emphasis_italic` secondo [brand-profile.md](brand-profile.md), ne mostra il nome nell'interfaccia e non sintetizza un corsivo mancante. Se un asset non è disponibile o non si carica, mostra esplicitamente il fallback effettivo e lascia disponibile `Genera`. Espone inoltre `cover_subtitle` come campo opzionale e lo rende nello stesso ruolo corsivo quando disponibile.

Per l'anteprima dei logo servire soltanto asset raster autorizzati. Quando il master dichiarato è SVG e nella stessa cartella esiste un PNG omonimo, usare il PNG come derivato di anteprima e indicarlo nel pannello Brand. Non servire SVG non sanitizzati e non sostituire il master usato nella produzione finale.

Esaminare poi `comments` e `overall_note`. I commenti sono richieste da interpretare, non modifiche già effettuate. Applicare le correzioni necessarie al manifest, ripetere i controlli editoriali e aggiornare la revisione se occorre.

Se `action` è `approve`, trattarla come richiesta esplicita ma lasciare che `process_review.py` esegua gli avanzamenti attestati coperti dallo scope ricevuto. Se restituisce `approval_blocked`, leggere lo status incluso, correggere il gate e mantenere il checkpoint. Non modificare stato o ricevute a mano e non richiedere un nuovo consenso quando il medesimo batch può essere rielaborato dopo una correzione tecnica non visuale.

## Ripresa e chiusura

Dopo l'applicazione il server registra l'esito in `session-state.json` e l'editor ricarica la base aggiornata senza refresh manuale. Chiudere il server quando la revisione termina o l'utente interrompe il lavoro. Se una risposta si perde, il processo si interrompe o compare un conflitto fra basi o schede, leggere [review-recovery.md](review-recovery.md) prima di agire.

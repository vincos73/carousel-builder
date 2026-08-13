# Recupero della revisione locale

Leggere questa reference soltanto dopo un'interruzione, una risposta HTTP persa, un conflitto fra schede o un errore di applicazione. Non usarla nel percorso normale.

`session-state.json` è la fonte durevole. L'output del server è soltanto una notifica immediata. Riavviare `review_server.py` con lo stesso manifest e la stessa cartella di sessione: il journal completa un eventuale commit interrotto prima di accettare nuovi invii.

Il browser salva bozza e ID idempotente prima della POST, mantiene recovery append-only separate per scheda e rimuove il pending soltanto quando lo stesso `feedback_id` risulta applicato. Il server conserva i batch in `feedback-batches/`, mantiene `feedback.json` come alias verificato dell'ultimo batch e riemette all'avvio un batch pendente. Non ricreare né modificare manualmente questi file.

Se la risposta HTTP si perde, confrontare l'ID del pending con `last_feedback_id` e `applied_feedback_id`. Se esiste un batch append-only, usare `last_feedback_path`; usare `feedback.json` soltanto per una sessione legacy. Un pending di un'altra scheda non deve cancellare le modifiche locali: esportare o conservare la recovery prima di ricaricare.

Quando la revisione del manifest o il checkpoint cambia, l'editor ricarica automaticamente soltanto se non esistono modifiche locali. In caso contrario blocca l'invio e conserva una recovery. Non chiedere un aggiornamento manuale della pagina e non forzare l'applicazione su una base diversa.

Se server, browser o applicazione continuano a fallire, non avanzare il workflow. Preservare fonte, profilo, testi approvati, manifest e artefatti validi; spiegare il risultato ancora disponibile e offrire ripetizione, fallback conversazionale o interruzione. Gli avanzamenti locali sono forward-only. Per correggere contenuto o proof dopo un avanzamento applicare il batch originale: lo script riapre atomicamente `bozza` per richieste editoriali/non classificabili o `testi_approvati` per modifiche solo visuali, comprese le sole enfasi tipografiche, conservando soltanto le ricevute ancora vere. Ripetere i checkpoint senza modificare a mano stato o ricevute. Non presentare artefatti parziali come consegna completa.

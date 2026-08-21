---
name: carousel-builder
description: Trasforma URL, articoli e testi in caroselli editoriali 4:5, guidando identità visiva e approvazione in editor locale o conversazione.
---

# Carousel Builder

Versione: **2.13.2**

Separare fonte, identità, testi, prova, produzione e QA. L'utente decide le scelte editoriali e visuali: il sistema le segnala, ma blocca solo errori tecnici, strutturali, di sicurezza o del workflow. Nel caso normale l'editor espone una sola azione primaria, `Genera`, conservando le ricevute durevoli. La richiesta iniziale autorizza solo la proposta editoriale.

Identità, logo, URL, firma e attribuzioni devono essere forniti o approvati dall'utente; non ricavarli da fonte, memoria o profilo personale.

Usare solo gli strumenti inclusi, senza installare pacchetti o scaricare browser, font o dipendenze. Risorse esterne solo da fonti approvate.

Il workflow è `bozza` → `testi_approvati` → `prova_visuale_approvata` → `rendering` → `qa` → `consegnato`. In `local-editor` non modificare stato o ricevute a mano: usare gli script documentati nelle reference. `adapter` e `layout` rispettano gli stessi checkpoint.

Prima di una mutazione o dopo recovery, eseguire internamente `carousel_status.py` con manifest e sessione. `next_action` diagnostica senza modificare file; non esporre stati intermedi o controlli riusciti all'utente.

## Routing delle istruzioni

Caricare solo ciò che serve alla fase corrente:

- leggere sempre [runtime-preflight.md](references/runtime-preflight.md) all'inizio;
- leggere [brand-onboarding.md](references/brand-onboarding.md) se manca l'identità e [brand-profile.md](references/brand-profile.md) per costruire o validare un profilo;
- leggere [editorial-workflow.md](references/editorial-workflow.md) e [semantic-emphasis.md](references/semantic-emphasis.md) prima di preparare i testi;
- leggere [visual-systems.md](references/visual-systems.md) prima di proporre il sistema grafico;
- leggere [visual-review.md](references/visual-review.md) e [workflow-state.md](references/workflow-state.md) nel percorso `local-editor`;
- leggere [cover-visual.md](references/cover-visual.md) e [carousel-schema.md](references/carousel-schema.md) dopo l'approvazione dei testi;
- leggere [production-qa.md](references/production-qa.md) prima della prova visuale e mantenerlo come contratto fino alla consegna.

## Percorso di revisione

Usare `local-editor` solo se è possibile eseguire Python 3.10 o successivo, aprire `127.0.0.1` nel browser dell'utente e ricevere gli eventi del server. `local-editor` è obbligatorio quando le capacità esistono: aprirlo subito una sola volta nella superficie già assegnata, senza chiedere conferma. Preferire il browser interno; non usare Chrome come fallback se il browser interno è disponibile. Non dichiararlo disponibile finché non è visibile.

Usare `conversation` quando almeno una capacità è realmente assente o fallisce. Mostrare sezioni Markdown normali e modificabili, mai HTML stampato, code fence o blocchi monospazio. Dichiarare il fallback e mantenere gli stessi checkpoint.

## Fase 0: preflight

1. Determinare gli output producibili e comunicarli in una frase.
2. Leggere tutta la fonte. Un URL autorizza la lettura di quell'URL, non di risorse estranee. Se non è leggibile, chiedere testo o documento; non colmare i vuoti.
3. Classificare fonte (`newsletter`, `article`, `notes`, `verbatim`) e sequenza (`narrative` o `sectional`); accettare gli alias legacy.
4. Validare il profilo fornito, costruirne uno con l'utente o usare quello neutro soltanto dopo una scelta esplicita.
5. Scegliere il percorso dalle capacità osservate. Non chiedere sistema visivo o copertina durante l'intake: proporli internamente e renderli modificabili nell'editor.

## Fase 1: profilo e testi

1. Costruire copertina e sequenza secondo [editorial-workflow.md](references/editorial-workflow.md). Nel percorso rapido mostrare insieme profilo e testi; nel guidato approvare prima il profilo.
2. Indicare profilo, fonte, `sequence_mode`, output, numero di slide e testi esatti. Ogni frase compiuta inizia su una nuova riga. Non mostrare manifest o note tecniche.
3. Selezionare internamente un solo sistema consigliato secondo [visual-systems.md](references/visual-systems.md). Offrire alternative solo su richiesta o incertezza e salvare la scelta in `visual_style_system`.
4. Usare `typographic` per default; `generated`/`provided` solo se l'utente ha richiesto o fornito un visuale. Nel percorso locale creare uno schema 1.4 `bozza`. Preparare una proposta pulita a 480 px: 180 caratteri con titolo e 320 senza come obiettivi editoriali; gli eccessi scelti dall'utente restano avvisi consultivi.
5. Avviare l’editor secondo [visual-review.md](references/visual-review.md), con `--return-thread-id`. Riutilizzare una sola tab, chiamare `markHandoff()` e restare in attesa al massimo 50 secondi; non terminare il turno né chiedere «fatto». Il batch è durevole. Il server applica automaticamente `approve`; `feedback` richiede interpretazione. All’evento, confermare ID, azione e prossimo passo, leggere `carousel_status.py` ed eseguire `process_review.py` solo se il batch è pendente.
   Se l’editor mostra un batch in attesa, trattarlo come consegna durevole: rileggere `session-state.json`, applicare il batch con lo stesso `feedback_id` e lasciare la scheda in handoff solo dopo aver verificato lo stato.
6. Elaborare un batch ancora pendente con `process_review.py <manifest> <feedback> --session-dir <session-dir>`. Per `feedback`, applicare commenti e correzioni dell'utente. Per `approve`, copy, ordine, profilo ed enfasi del batch sono definitivi: non confrontarli con fonte o bozze, correggerli, ripristinarli o riaprire il checkpoint per valutazioni editoriali, tipografiche o di accessibilità. Se l’approvazione automatica è già registrata, continuare dal `next_action` senza riprocessarla. Dopo l'approvazione bloccano soltanto errori tecnici, strutturali, di sicurezza o del workflow.
7. Dopo ogni batch lasciare che l'editor ricarichi il manifest. `Genera` può registrare entrambi i checkpoint; altrimenti avanza solo il primo. A `prova_visuale_approvata`, confermare l'approvazione, eseguire `next_action` e proseguire senza un'altra richiesta. Non inviare un nuovo batch di correzione per iniziativa dell'agente dopo `approve`; esporre soltanto eventuali blocchi tecnici o strutturali.
8. Nel percorso conversazionale mostrare slide cambiate e sequenza completa, poi offrire approvazione o modifica.

## Fase 2: prova visuale

1. Saltare questa fase se il percorso combinato ha già portato il manifest a `prova_visuale_approvata`. Altrimenti, se `cover_mode` richiede un visuale, estrarre 2-3 concetti e tradurli in una sola metafora secondo [cover-visual.md](references/cover-visual.md), quindi generare o acquisire l'immagine soltanto ora. Nel percorso locale collegarla attraverso `attach_cover_asset.py`, mai modificando il manifest a mano. Se la modalità è `typographic` o l'immagine non è producibile, mantenere una copertina tipografica completa.
2. Applicare la firma del sistema selezionato alle card interne e alla chiusura, mai alla copertina. Convertire le enfasi approvate in campi espliciti e rimuovere gli asterischi.
3. Preparare il manifest conforme a [carousel-schema.md](references/carousel-schema.md), con produzione, accessibilità e prova canonica: copertina, card interna più densa e chiusura se presente.
4. Mostrare il campione a 480×600 e a risoluzione leggibile secondo [production-qa.md](references/production-qa.md). Segnalare font sostituiti, fit, contrasto, crop e firma strutturale senza trasformarli in certificazioni automatiche.
5. Mostrare la prova e offrire `Genera`, cambio grafico o ritorno ai testi. La cover visuale usa titolo a sinistra e immagine a destra, senza overlay. Nel locale restare in attesa attiva a ogni prova. Densità, overflow, enfasi, contrasto, palette, font, crop, alt text e campione non visto sono informativi; bloccano solo rendering non costruibile, struttura, modifiche, asset, sessione o workflow non validi.
6. Elaborare il batch visuale con `process_review.py`: avanza a `prova_visuale_approvata` quando fingerprint, browser Chromium e produttore superano i gate tecnici. Il campione e `proof.style_system_verified` restano evidenza diagnostica, non gate visuali. Dopo una modifica grafica mostrare una nuova prova; non riaprire i testi se il copy è identico.

## Fase 3: produzione, QA e consegna

1. Leggere integralmente [production-qa.md](references/production-qa.md). Nel percorso locale seguire anche [workflow-state.md](references/workflow-state.md) e avanzare a `rendering` soltanto con proof corrente e output attesi dichiarati. Non concludere il turno negli stati `prova_visuale_approvata`, `rendering` o `qa`: continuare fino a `consegnato` oppure a un blocco concreto documentato.
2. Nel percorso locale esportare dallo stesso DOM `.slide-preview` e dallo stesso CSS approvati, con l'invocazione documentata in [production-qa.md](references/production-qa.md#invocazione-local-editor). Non creare un secondo template. Richiedere parità esatta di contenuto, revisione, fingerprint, geometria e pixel prima e dopo la cattura.
3. Se manca un controllo tipografico affidabile o il produttore non implementa il sistema selezionato, non generare card complete: consegnare un layout dettagliato dichiarando il limite.
4. Controllare automaticamente tutte le slide. Generare e ispezionare la contact sheet soltanto se è tra gli output richiesti o serve davvero alla revisione umana; l'apertura manuale resta advisory. Dopo correzioni richieste dall'utente ripetere proof e transizioni prima di `rendering`; non riesportare da `qa` o `consegnato`.
5. Dopo l'export usare `finalize_delivery.py` con il risultato di render. Nel percorso normale lo script genera da solo il report QA tecnico e copia i digest dall'evidenza attestata; `--qa-report` resta un override avanzato per registrare controlli umani o diagnostici. Revisione, fingerprint, parità, struttura e digest restano bloccanti; font e campione umano restano consultivi. Se un gate tecnico fallisce conserva lo stato `qa`. Non presentare output parziali come finali.
6. Consegnare solo artefatti realmente prodotti e aperti, indicando quantità, dimensioni, formato e modalità. Creare uno ZIP soltanto su richiesta esplicita.

## Contratto editoriale essenziale

- Usare solo informazioni della fonte, salvo richiesta esplicita di ricerca. Conservare numeri, nomi, cautele, condizioni e attribuzioni; non inventare causalità o certezza. Non usare em dash nei testi italiani.
- Mantenere normalmente 5-6 slide di contenuto. In `verbatim` non riscrivere senza autorizzazione. In `narrative` lasciare vuoti i titoli interni; in `sectional` usarli solo quando aiutano l'autonomia.
- Includere sempre la copertina e, per `newsletter` e `article`, la chiusura salvo scelta diversa. Il sottotitolo è opzionale e mai inventato. Generare la CTA dalla fonte corrente, non dal profilo riutilizzabile.
- Separare le frasi con veri ritorni a capo, senza righe vuote; nel JSON usare l'escape `\n` che viene decodificato come a capo, mai la sequenza letterale barra inversa + `n`. Il server normalizza comunque i manifest legacy doppiamente escapati prima di mostrarli nell'editor. Non spezzare abbreviazioni, iniziali, decimali, domini o URL. Nel render ogni frase è un blocco con `sentence_gap_em: 0.6` oltre a `body_line_height`.
- Usare i font approvati nei ruoli `display`, `body` ed eventuale `emphasis_italic`; non sintetizzare il corsivo. Se un font manca, mostrare il fallback e consentire `Genera`. Dopo l'approvazione visuale, disponibilità e differenze metriche fra sistemi sono avvisi non bloccanti; blocca una differenza reale fra prova e output. `*_bold`, `*_italic`, `*_underline` e `*_accent` contengono locuzioni esatte, distinte e non sovrapposte. Il grassetto suggerito resta rimovibile e non blocca l'approvazione.
- Usare HTML/CSS/SVG deterministici. Le slide interne restano tipografiche salvo richiesta esplicita; gli SVG strutturali del sistema sono ammessi. Numerare ogni pagina in alto a destra dentro la safe area; nella cover split il numero resta in alto a destra nella colonna testuale e non invade l'immagine.
- Il master è 1080×1350 in 4:5, l'export 1440×1800 e la prova 480×600, senza reflow. Per rapporti diversi creare una variante separata e una nuova approvazione. L'adattamento automatico non supera l'8%; altrimenti si rivede il copy.
- Verificare accessibilità, ordine di lettura, trascrizione o alt text, contrasto e leggibilità a dimensione feed. Non affidare significati soltanto a colore, peso, corsivo, famiglia o posizione.

## Profili, modifiche e recovery

Un profilo riutilizzabile contiene regole, non testi della singola fonte. Logo e font proprietari restano asset separati. Dopo l'approvazione offrire una sola volta il salvataggio come `<nome-brand>-carousel-brand.json`; non modificare la skill né incorporarvi asset personali.

Per modifiche testuali mostrare le slide cambiate e poi la sequenza aggiornata. Per modifiche solo grafiche non riaprire i testi, ma richiedere una nuova prova. Riutilizzare la cover soltanto se tesi, metafora e composizione restano invariate.

In caso di errore non avanzare lo stato e preservare gli artefatti. Seguire [review-recovery.md](references/review-recovery.md) soltanto dopo un'interruzione o conflitto. Dopo un timeout, riavviare il server con lo stesso manifest/sessione, applicare il batch durevole e riprendere senza nuova approvazione. Rielaborare lo stesso batch per errori tecnici. Le correzioni riaprono `bozza` per copy, ordine o profilo, oppure `testi_approvati` per stile, logo o enfasi. Ripetere solo i checkpoint invalidati; non modificare stato o ricevute.

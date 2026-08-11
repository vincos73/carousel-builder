---
name: carousel-builder
description: Trasforma URL, articoli, newsletter, note e testi in caroselli editoriali verticali 4:5 per Instagram, LinkedIn e altri canali social. Configura o riutilizza un'identità visiva, guida l'approvazione editoriale, usa un editor HTML locale quando la sessione supporta Python, browser locale e ricezione degli eventi, e passa automaticamente alla revisione conversazionale negli altri ambienti.
---

# Carousel Builder

Versione: **2.8.9**

Creare caroselli editoriali separando fonte, profilo visivo, revisione editoriale, approvazione dei testi e produzione grafica. Adattare la superficie di revisione alle capacità effettive della sessione, mantenendo invariati metodo editoriale e checkpoint.

Usare soltanto strumenti già disponibili nella sessione. Non installare pacchetti e non scaricare browser, font o dipendenze. Nel percorso locale eseguire esclusivamente `scripts/review_server.py`, `scripts/apply_review.py` e, dopo la prova visuale approvata, `scripts/export_review_pdf.cjs`, inclusi e verificati nella skill. Non eseguire altri script della skill. Recuperare risorse esterne soltanto quando l'utente fornisce o approva esplicitamente la fonte e lo strumento lo consente.

Non incorporare identità, logo, URL, firma o attribuzioni della skill nei caroselli senza approvazione esplicita. Non ricavare il brand dalla fonte, dalla memoria o dal profilo personale dell'utente.

Richiedere due approvazioni distinte prima del rendering completo: prima profilo e testi, poi una prova visuale. Una richiesta iniziale come «crea un carosello» autorizza la proposta editoriale, non la produzione grafica.

Gestire il lavoro con questi stati: `bozza` → `testi_approvati` → `prova_visuale_approvata` → `rendering` → `qa` → `consegnato`. Non avanzare di stato senza il relativo via libera o senza aver completato il controllo previsto.

## Selezione del percorso di revisione

Adattarsi alle capacità effettivamente disponibili, non al solo nome del prodotto o a un'ipotesi sull'ambiente:

1. Usare `local-editor` soltanto quando è possibile eseguire Python 3.10 o successivo, aprire un indirizzo `127.0.0.1` nel browser dell'utente e ricevere il batch dal server locale.
2. Usare `conversation` quando Python, browser locale o ricezione del batch non sono disponibili. Mostrare normali sezioni Markdown modificabili attraverso la chat, senza code fence, blocchi monospazio o HTML stampato come testo.

Quando tutte e tre le capacità sono disponibili, `local-editor` è obbligatorio: aprire l'editor nello stesso turno appena manifest e preflight sono pronti. Non fermarsi a un'anteprima testuale, non chiedere all'utente se desidera aprirlo e non scegliere `conversation` per comodità. Il fallback conversazionale è ammesso soltanto dopo aver osservato l'indisponibilità o il fallimento di almeno una capacità necessaria.

Se l'ambiente espone esplicitamente le proprie capacità, usarle. Altrimenti verificare prima le capacità necessarie con controlli non invasivi. Non dichiarare disponibile un editor finché non è stato effettivamente aperto e reso visibile all'utente.

## Fase 0: preflight e orientamento

1. Leggere [references/production-qa.md](references/production-qa.md), risolvere prima gli eventuali runtime e librerie già configurati o inclusi nell'ambiente e determinare quali risultati sono realisticamente producibili nella sessione: immagini di copertina, card con tipografia controllata, PNG, PDF o solo layout dettagliato. Non assumere che l'interprete Python predefinito rappresenti tutte le capacità disponibili.
2. Descrivere i risultati previsti in una frase, senza esporre nomi tecnici degli strumenti.
3. Leggere [references/brand-onboarding.md](references/brand-onboarding.md) e [references/visual-systems.md](references/visual-systems.md). Se la richiesta è incompleta, mostrare l'introduzione operativa prevista. Se contiene già fonte e profilo JSON, brand pack, tema neutro o indicazioni visive sufficienti, evitare l'introduzione estesa e procedere.
4. Selezionare `local-editor` o `conversation` con le regole precedenti. Leggere [references/visual-review.md](references/visual-review.md) per il percorso locale. Dichiarare il fallback conversazionale quando il percorso locale non è disponibile.

## Fase 1: fonte, brand e anteprima

1. Leggere interamente la fonte. Il conferimento di un URL autorizza la lettura di quell'URL, non di risorse estranee. Se la fonte non è leggibile, non colmare i vuoti: chiedere di incollare il testo, caricare il documento o fornire una versione accessibile.
2. Determinare la modalità della fonte:
   - `newsletter`: più notizie o sezioni distinte;
   - `article`: un articolo, paper o testo argomentativo;
   - `notes`: note o testo da trasformare in sequenza;
   - `verbatim`: testo da riprodurre senza riscrittura, diviso sui doppi a capo.
   Accettare `rework` e `social` come alias legacy rispettivamente di `notes` e `verbatim`.
3. Determinare la modalità della sequenza con [references/editorial-workflow.md](references/editorial-workflow.md):
   - `narrative`: una tesi sviluppata in passaggi dipendenti;
   - `sectional`: sezioni o notizie autonome, comprensibili anche isolate.
   Non confondere la modalità della fonte con quella della sequenza: un articolo è normalmente narrativo, ma può essere sezionale se la struttura della fonte lo richiede.
4. Risolvere il profilo di brand:
   - validare e usare il profilo JSON o il brand pack fornito;
   - usare il profilo approvato nel lavoro corrente;
   - configurare un nuovo profilo con il percorso rapido o guidato di [references/brand-onboarding.md](references/brand-onboarding.md);
   - usare il profilo neutro di [references/brand-profile.md](references/brand-profile.md) solo dopo una scelta esplicita.
5. Leggere [references/editorial-workflow.md](references/editorial-workflow.md) e costruire copertina e sequenza secondo `sequence_mode`.
6. Leggere [references/semantic-emphasis.md](references/semantic-emphasis.md). Per impostazione predefinita proporre nelle card interne una breve unità `*_bold` con il carattere principale, ma trattarla come scelta editoriale liberamente rimovibile dall'utente e mai come requisito di approvazione. Consentire più trattamenti nello stesso testo quando riguardano parole o locuzioni distinte; impedire soltanto che la stessa unità testuale riceva più stili o che due selezioni si sovrappongano. Usare `*_italic` soltanto quando il profilo risolve una vera variante corsiva del carattere principale oppure un carattere corsivo secondario approvato. Accettare `*_serif` come alias legacy. Rendere `*_accent` come evidenziatore adattivo del colore di brand, non come semplice testo colorato. Non sintetizzare il corsivo inclinando un font privo della variante reale.
7. Nel percorso rapido, preparare nella stessa revisione prima `Anteprima profilo brand` e poi `Anteprima testi`. Usare un solo checkpoint editoriale che richiede l'approvazione di entrambi; accettare correzioni o approvazioni separate senza creare due passaggi obbligatori.
8. Nel percorso guidato, ottenere prima l'approvazione del profilo e poi mostrare `Anteprima testi`.
9. Nell'anteprima testuale indicare:
   - profilo usato;
   - master 1080×1350, export previsto e numero totale di slide;
   - titolo esatto della copertina;
   - titolo e testo esatti di ogni slide;
   - chiusura esatta, quando prevista;
   - ogni frase compiuta su una nuova riga.
10. Mostrare soltanto contenuti destinati alle slide, oltre alle informazioni minime su profilo, formato, fonte, `sequence_mode` e approvazione. Non esporre manifest, prompt visuali o note tecniche.
11. Mostrare le tre prove di [references/visual-systems.md](references/visual-systems.md) con lo stesso contenuto rappresentativo e la stessa identità approvata. Preselezionare il sistema risolto dal manifest o dal profilo, consentire il confronto e salvare la scelta del singolo carosello in `visual_style_system`. Considerare valida una prova soltanto quando rende visibile la firma strutturale obbligatoria del sistema, non quando ne mostra soltanto nome, palette o tipografia.
12. Se è selezionato `local-editor`, creare il manifest in stato `bozza` e completare il preflight visuale descritto in [references/visual-review.md](references/visual-review.md) prima di consegnare l'editor: ogni riassunto generato con titolo deve contenere al massimo 180 caratteri, ogni riassunto generato senza titolo al massimo 320 caratteri e nessuna slide iniziale deve mostrare avvisi di densità o overflow in uno dei tre sistemi proposti. Correggere o dividere il copy finché limiti e fit reale sono puliti, senza ridurre il carattere oltre l'8%. Poi avviare l'editor e aprirlo immediatamente nel browser. Mostrare nell'editor le varianti di logo realmente disponibili, una sintesi dei caratteri usati e i comandi contestuali per grassetto, corsivo, sottolineatura, evidenziatore e commento. Non limitarsi a stampare il codice HTML nella chat e non duplicare l'intera anteprima, salvo richiesta dell'utente o fallback.
13. Nell'editor invitare l'utente a scegliere `Invia correzioni` oppure `Approva profilo e testi`. Dichiarare chiaramente che la copertina finale sarà mostrata in una prova visuale separata soltanto dopo l'approvazione dei testi e potrà usare un'immagine generata, un'immagine fornita o una composizione tipografica. Trattare l'invio delle correzioni come feedback, mai come approvazione implicita. Nel percorso `local-editor`, non terminare il turno e non chiedere all'utente di tornare in chat con messaggi come «fatto»: mantenere il task in ascolto dell'evento del server secondo [references/visual-review.md](references/visual-review.md).
14. Appena il server segnala il batch, dare subito un riscontro nella chat: per `Invia correzioni`, confermare che le correzioni sono state ricevute e si stanno applicando; per `Approva profilo e testi`, confermare che l'approvazione è stata ricevuta e che seguono i controlli prima della prova visuale. Usare il percorso append-only restituito dall'evento quando disponibile, applicare poi le modifiche dirette con `scripts/apply_review.py`, esaminare e risolvere tutti i commenti ricevuti e comunicare in chat l'esito e il prossimo checkpoint. Conservare esattamente il testo scritto dall'utente salvo incompatibilità dichiarata con fonte, modalità `verbatim` o vincoli di produzione.
15. Dopo ogni batch, ripetere i controlli editoriali, aggiornare il manifest e far ricaricare l'editor. Non avanzare oltre `bozza` finché l'utente non ha richiesto esplicitamente l'approvazione e tutti i controlli sono superati.
16. Se l'utente richiede l'approvazione ma resta un problema bloccante, mantenere `bozza`, mostrare il problema nell'editor o in chat e chiedere una correzione.
17. Nel fallback conversazionale, usare il flusso originale: mostrare prima le slide cambiate e poi l'intera anteprima aggiornata; invitare a scegliere `Approva profilo e testi`, `Modifica il profilo` oppure `Modifica i testi`. Usare titoli e paragrafi Markdown normali; non racchiudere i testi delle slide in code fence o blocchi monospazio.

## Fase 2: prova visuale

1. Leggere [references/cover-visual.md](references/cover-visual.md). Ricavare 2-3 concetti dalle slide e tradurli in una sola metafora visiva.
2. Usare il sistema visivo scelto secondo [references/visual-systems.md](references/visual-systems.md) come contratto eseguibile di composizione. Renderizzare la sua firma strutturale sulle card interne e sulla chiusura, ma non sulla copertina: cornice, costellazione e indice modulare non devono sovrapporsi al visuale di cover. Creare un'immagine soltanto per la copertina e soltanto se è disponibile un generatore immagini; altrimenti usare un'immagine fornita oppure una copertina `typographic` completa basata su gerarchia, palette e tipografia.
3. Convertire le eventuali enfasi approvate in campi espliciti e rimuovere gli asterischi dai testi finali.
4. Preparare una scheda di produzione conforme a [references/carousel-schema.md](references/carousel-schema.md), includendo profilo risolto, CTA e stato del lavoro.
5. Creare una prova composta da copertina, card più densa e chiusura quando prevista. Usare card renderizzate soltanto con controllo tipografico affidabile e con supporto esplicito al `visual_style_system` selezionato; altrimenti mostrare la composizione e i tre layout dettagliati dichiarando il limite. Se la generazione immagini non è disponibile, renderizzare normalmente la copertina `typographic` o con l'immagine fornita quando il renderer lo consente. Verificare che la cover sia priva degli elementi strutturali del sistema e che card interna e chiusura ne mostrino la firma obbligatoria.
6. Verificare la prova a dimensione feed e a risoluzione leggibile secondo [references/production-qa.md](references/production-qa.md).
7. Mostrare la prova e invitare l'utente a scegliere `Approva la prova visuale`, `Cambia la direzione grafica` oppure `Torna ai testi`. Nel percorso `local-editor`, mantenere il task in attesa attiva dell'evento anche in questo checkpoint e in ogni prova successiva, applicando il controllo durevole descritto in [references/visual-review.md](references/visual-review.md); non concludere il turno né chiedere all'utente di scrivere «fatto».
8. Dopo qualsiasi modifica grafica, produrre e mostrare una nuova prova. Non riaprire l'approvazione dei testi se il testo approvato è rimasto identico.

## Fase 3: produzione completa

1. Dopo `Approva la prova visuale`, produrre l'intera sequenza con un renderer o adapter compatibile quando disponibile. Nel percorso `local-editor`, esportare il PDF con `scripts/export_review_pdf.cjs` dal medesimo DOM `.slide-preview` e dal medesimo CSS mostrati all'utente, usando l'[invocazione completa documentata nel QA](references/production-qa.md#invocazione-local-editor): non creare un secondo template HTML/CSS. L'export deve richiedere una prova approvata e ancora legata al fingerprint corrente di contenuto e asset, acquisire revisione, stato del workflow e snapshot canonico, confrontare anteprima e produzione sia nella geometria normalizzata sia nei pixel catturati e ricontrollare il contratto immediatamente prima di finalizzare il PDF. Interrompersi alla prima differenza. Un produttore è compatibile soltanto se dichiara e implementa il `visual_style_system` selezionato; palette e font corretti non compensano l'assenza della sua firma strutturale.
2. Se non è disponibile un controllo tipografico affidabile, non generare card complete come immagini: consegnare il layout dettagliato, slide per slide, pronto per Canva, Figma o un editor equivalente.
3. Applicare integralmente il controllo di [references/production-qa.md](references/production-qa.md). Per sequenze fino a 10 slide, ispezionare visivamente tutte le card oltre alla contact sheet completa, verificare l'assenza della firma strutturale sulla copertina e confrontare quella delle card interne e della chiusura con la prova approvata.
4. Correggere e rigenerare gli artefatti quando il controllo trova tagli, sovrapposizioni, contrasto insufficiente, asset mancanti o difformità dai testi approvati.
5. Consegnare l'anteprima finale e gli artefatti prodotti, indicando numero, dimensioni, formato e modalità di produzione. Creare un archivio ZIP soltanto su richiesta esplicita.

## Regole editoriali

- Usare esclusivamente informazioni presenti nella fonte, salvo richiesta esplicita di ricerca o integrazione.
- Scrivere nella lingua dell'utente o in quella richiesta, traducendo anche onboarding, etichette e comandi di conferma.
- Mantenere massimo 5-6 slide di contenuto, salvo richiesta diversa.
- Conservare numeri, nomi propri, cautele, condizioni e attribuzioni.
- Non introdurre priorità, rapporti causali, gradi di certezza o conclusioni non presenti nella fonte.
- Non usare em dash nei testi italiani.
- Nel manifest inserire una nuova riga dopo ogni frase compiuta, senza righe vuote; non spezzare abbreviazioni, iniziali, decimali, domini o URL.
- Non riscrivere il testo in modalità `verbatim` senza autorizzazione.
- Includere sempre la copertina.
- La copertina contiene sempre il titolo. Il sottotitolo è opzionale: usarlo soltanto quando l'utente lo fornisce o lo approva esplicitamente, senza inventarlo. Renderizzarlo nel ruolo `emphasis_italic` risolto, subordinato al titolo.
- Ogni uso di Playfair Display nel ruolo `emphasis_italic` è sempre in corsivo; non usare la variante tonda. Lo stesso ruolo può usare la vera variante italic del carattere principale oppure un altro carattere corsivo previsto dal profilo.
- Nel rendering trattare ogni frase come un blocco distinto e aggiungere dopo ogni frase, tranne l'ultima, uno spazio verticale di `sentence_gap_em: 0.6` oltre alla normale interlinea `body_line_height`. Non simulare questa distanza con righe vuote e non confonderla con l'andata a capo automatica.
- In modalità `narrative`, lasciare vuoti i titoli delle slide interne e non renderizzare etichette tecniche, nomi del layout o eyebrow decorativi. Il testo deve costruire una progressione continua.
- Inserire sempre la numerazione progressiva delle pagine nell'angolo superiore destro, inclusi copertina, slide interne e chiusura, dentro la safe area.
- Costruire la struttura delle card con HTML/CSS/SVG deterministici. Usare immagini generate soltanto come asset opzionale di copertina; in loro assenza usare una copertina tipografica o un'immagine fornita.
- Trattare `visual_style_system` come un requisito grafico verificabile, non come semplice metadato. La firma strutturale definita in `visual-systems.md` deve restare riconoscibile sulle card interne e sulla chiusura, ma deve essere assente dalla copertina per non sovrapporsi al visuale; ogni violazione non supera il QA.
- In modalità `sectional`, usare titoli interni quando aiutano slide autonome; non usare comunque etichette tecniche o nomi del layout.
- Per il copy generato dalla skill, non superare mai 180 caratteri nel corpo di una card interna con titolo o 320 caratteri senza titolo. Accorciare o dividere la slide prima di aprire l'editor. In modalità `verbatim` o con testo scritto dall'utente, non riscrivere in silenzio: segnalare il superamento e proporre una divisione.
- Per impostazione predefinita usare un solo visuale in copertina. Mantenere le slide interne pulite e tipografiche, senza illustrazioni SVG o disegni decorativi autonomi. Restano consentiti gli SVG strutturali del sistema visivo. Visuali interni richiedono una richiesta esplicita e una nuova prova visuale coerente per tecnica e stile.
- Usare il carattere approvato nel profilo, non un font fisso della skill. Qualsiasi sostituzione deve essere nominata, motivata e approvata prima della prova visuale.
- Applicare il ruolo `display` a copertina e titoli e il ruolo `body` a testi, CTA e metadati. Nei profili legacy usare `sans` per entrambi i ruoli; non confondere questa gerarchia con il ruolo corsivo opzionale, che può appartenere alla stessa famiglia del body oppure a un secondo carattere approvato.
- Includere la chiusura per `newsletter` e `article`, salvo scelta diversa nel profilo.
- Generare la CTA dalla fonte corrente quando `outro.copy_mode` è `generate_from_source`; non salvarne titolo e corpo nel profilo riutilizzabile.
- Contare la chiusura nel numero totale e mostrarla prima dell'approvazione.
- Non inserire Markdown o asterischi tipografici nei testi delle slide. Nell'editor usare i comandi diretti; nella revisione conversazionale descrivere separatamente le locuzioni da registrare nei campi `*_bold`, `*_italic`, `*_underline` e `*_accent`.
- Nelle card narrative interne proporre di default una `summary_bold` con una locuzione semantica breve e completa per dare ritmo al testo. Fare lo stesso nelle card sezionali con corpo, ma consentire sempre all'utente di rimuoverla senza avvisi e senza bloccare l'approvazione. Consentire grassetto, corsivo, sottolineatura ed evidenziatore su parole o locuzioni distinte; non applicare più stili alla stessa unità e non sovrapporre le selezioni.
- Non inventare logo, sito, firma, tagline, colori o attribuzioni.
- Non presentare il profilo neutro come identità dell'utente.
- Usare come master il canvas 1080×1350 in rapporto 4:5. Esportare in alta definizione a 1440×1800 applicando la stessa scala proporzionale, senza cambiare densità o impaginazione.
- Trattare il 4:5 come master multipiattaforma, non come formato universale. Se il canale o placement richiesto usa un rapporto diverso, verificare le specifiche correnti, derivare una variante separata e sottoporla a una nuova prova visuale. Non deformare o ritagliare silenziosamente il master.
- Consentire un adattamento tipografico automatico massimo dell'8%. Se il testo non entra ancora, fermarsi e richiedere una revisione del copy; non ridurre ulteriormente il carattere.

## Profili riutilizzabili

Accettare sito, brand kit, brief informale, JSON o brand pack. Tradurre gli input nello schema di [references/brand-profile.md](references/brand-profile.md).

Un profilo JSON deve contenere regole riutilizzabili, non testi legati a una singola fonte. Logo e font proprietari non sono incorporati nel JSON: quando servono per la portabilità, offrire un brand pack con JSON e asset, soltanto su richiesta esplicita.

Dopo l'approvazione di un nuovo profilo, offrire una volta di salvarlo come `<nome-brand>-carousel-brand.json`. Non modificare la skill e non incorporarvi asset personali.

## Modifiche

Per revisioni testuali, mostrare le slide cambiate e poi l'intera sequenza aggiornata, quindi attendere un nuovo via libera. Per modifiche esclusivamente grafiche, aggiornare il profilo o la scheda di produzione senza riaprire l'approvazione dei testi, ma richiedere sempre una nuova approvazione della prova visuale.

Riutilizzare il visuale di copertina se una modifica testuale non cambia tesi, metafora o composizione. Rigenerarlo quando cambiano fonte, tesi centrale, metafora o direzione visiva.

## Recupero e interruzioni

Se una lettura, generazione, esportazione o verifica fallisce:

1. non avanzare lo stato del lavoro;
2. preservare fonte, profilo, testi approvati, manifest e artefatti validi già prodotti;
3. spiegare in linguaggio semplice cosa non è riuscito e quale risultato resta disponibile;
4. offrire `Riprova`, `Usa il fallback dichiarato`, `Torna allo stato precedente` oppure `Interrompi`;
5. non presentare mai artefatti parziali come consegna completa.

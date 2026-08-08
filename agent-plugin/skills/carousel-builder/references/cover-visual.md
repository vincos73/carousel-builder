# Visuale di copertina

Definire la copertina dopo l'approvazione di profilo e testi e prima della prova visuale. Derivare soggetto, scena e metafora dalla fonte corrente; derivare stile, tecnica, palette e tono da `brand.visual_direction` e dagli altri campi del profilo. Scegliere `generative` soltanto se la sessione può generare immagini, `provided` per un asset dell'utente oppure `typographic` in assenza di entrambi. Per impostazione predefinita non generare illustrazioni decorative per le slide interne; restano consentiti gli SVG strutturali del sistema visivo.

## Estrazione

1. Elencare i concetti presenti nelle slide.
2. Ordinarli per centralità e capacità distintiva.
3. Selezionarne massimo tre in `cover_visual_concepts`.
4. Tradurre la relazione tra i concetti in una scena, un oggetto o un sistema fisico e salvarla in `cover_visual_metaphor`.
5. Evitare di riutilizzare automaticamente metafore di lavori precedenti.

Tenere separate le decisioni: la fonte determina cosa rappresentare; il profilo determina come rappresentarlo. Non cambiare concetti o metafora per adattarli a uno stile preferito.

Per newsletter eterogenee, rappresentare il tema dominante o il filo comune; evitare collage. Per articoli, rappresentare tesi, tensione o meccanismo causale. Per note, rappresentare la trasformazione principale senza aggiungere concetti.

## Prompt

Preparare il prompt solo in modalità `generative`. In modalità `provided`, verificare che l'asset supporti metafora, crop e contrasto. In modalità `typographic`, tradurre metafora e composizione in gerarchia testuale, superfici e segni del sistema scelto, senza inventare un'immagine.

Costruire il prompt con:

```text
Uso: illustrazione editoriale per la copertina di un carosello 4:5.
Tema centrale: [cover_title].
Concetti selezionati: [cover_visual_concepts].
Metafora: [cover_visual_metaphor].
Scena e soggetti: [elementi specifici della fonte].
Direzione visiva: [brand.visual_direction.mode e brand.visual_direction.description].
Riferimenti approvati: [brand.visual_direction.references, se presenti].
Palette: [colori del profilo].
Composizione: [composizione coerente con profilo, metafora e spazio destinato al titolo]; margini generosi; nessun elemento importante vicino ai bordi.
Vincoli: [brand.visual_direction.avoid]; nessun testo, lettera, numero, logo, watermark, interfaccia, cornice o mockup di slide.
```

## Regole

- Preferire una scena unificante a un collage di simboli.
- Rispettare la modalità scelta: non trasformare automaticamente uno stile fotografico in illustrazione o uno stile materico in grafica geometrica.
- Mantenere una sola tecnica visiva. Se l'utente richiede visuali anche nelle slide interne, non mescolare una copertina materica o illustrata con doodle SVG generici; produrre una nuova prova che dimostri coerenza tra le card interessate.
- Se la direzione visiva manca nel profilo personalizzato, chiederla prima di generare. Per il profilo neutro usare `editorial-geometric`.
- Evitare robot, cervelli luminosi e circuiti generici se non necessari alla tesi.
- Non imitare lo stile di artisti viventi o brand non autorizzati.
- In modalità `generative` o `provided`, preferire un'immagine 4:5 di almeno 1440×1800. Se lo strumento produce un rapporto diverso, dichiararlo e mantenere soggetti ed elementi essenziali dentro una safe area compatibile con il crop 4:5.
- Salvare un'immagine usata accanto al manifest o in `assets/`, mai nella cartella finale che il renderer ricrea.
- Dopo il rendering di un'immagine, correggere prima `cover_image_position`; rigenerarla o richiedere un altro asset solo se il problema è compositivo.

## Approvazione

Inserire il visuale nella prova con copertina, card più densa e chiusura. Non avviare il rendering completo prima dell'approvazione della prova. Se l'utente cambia metafora, stile, composizione o crop, aggiornare il visuale e mostrare una nuova prova senza modificare i testi approvati.

Se la sessione non può generare immagini, usare la copertina `typographic` o un asset `provided`. Se non è disponibile un renderer, mostrare metafora, composizione, palette e ingombri come layout dichiarato. Non presentare una descrizione o un segnaposto come immagine prodotta.

# Enfasi semantica

Usare l'enfasi tipografica soltanto quando il profilo approvato prevede un secondo carattere e il cambio aggiunge significato. Proporla nell'anteprima mediante asterischi e consentire all'utente di spostarla o eliminarla. Applicare nel renderer soltanto le scelte approvate.

## Sintassi

- `Il cambiamento è *già iniziato*` rende soltanto «già iniziato» nel secondo carattere approvato del profilo.
- Usare gli asterischi solo per il cambio di font, non per grassetto o corsivo Markdown.
- Racchiudere unità semantiche complete e usare massimo due segmenti per card.
- Dopo l'approvazione, rimuovere gli asterischi e compilare `cover_title_serif`, `title_serif` o `summary_serif`.

## Criteri

- Lasciare il testo interamente nel carattere primario quando manca un secondo font approvato o quando il cambio non aggiunge significato.
- Non introdurre automaticamente un serif in un profilo che prevede un solo sans.
- Usare il secondo carattere per contrasto, svolta, voce espressiva o concetto memorabile.
- In modalità `narrative`, privilegiare una gerarchia ottenuta con peso, dimensione e spazio. L'enfasi con un secondo font resta facoltativa.
- Usare i campi `*_accent` per rilievo cromatico indipendente dal font.
- Non assegnare automaticamente accenti cromatici. Usarli soltanto quando richiesti o approvati nella prova visuale.
- Non affidare informazioni essenziali al solo cambio di font o colore: il testo deve conservare lo stesso significato anche senza enfasi visuale.
- Non scegliere parole in base a lunghezza, maiuscole o frequenza.
- Non spezzare nomi propri, denominazioni, modelli o locuzioni.
- Verificare che ogni frase indicata compaia esattamente nel testo.

Esempio:

```json
{
  "title": "La lezione è operativa",
  "title_serif": ["è operativa"],
  "title_accent": []
}
```

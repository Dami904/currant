"""The evaluation side of the project: code allowed to see both the claim store and the sealed
labels. Pipeline modules (crawl, extract, store, serv) must never import `currant.evalset`; this
package is where the two meet, deliberately."""

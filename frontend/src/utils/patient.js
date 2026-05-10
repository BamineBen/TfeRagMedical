/**
 * Utilitaires de nommage patient — source unique de vérité côté frontend.
 *
 * Règle : {ID}_{NOM}_{Prenom}.pdf → 'Jean MARTIN'
 */

const _ID_RE = /^(\d+|[A-Z]\d+|NOTE)$/;

function _parseParts(source) {
    const base = source.replace(/\.\w+$/, '');
    const parts = base.split('_');

    let start = 0;
    for (let i = 0; i < parts.length; i++) {
        if (_ID_RE.test(parts[i])) {
            start = i + 1;
        } else {
            break;
        }
    }
    const relevant = parts.slice(start);

    if (!relevant.length) return [[], []];

    const nomParts = [];
    const prenomParts = [];
    let foundPrenom = false;
    for (const p of relevant) {
        if (!foundPrenom && p === p.toUpperCase() && p.length >= 2) {
            nomParts.push(p);
        } else {
            foundPrenom = true;
            prenomParts.push(p);
        }
    }
    return [nomParts, prenomParts];
}

/**
 * Extrait le nom affiché depuis le nom de fichier source.
 * 'P00011_MARTIN_Jean_Claude.pdf' → 'Jean Claude MARTIN'
 */
export function extractPatientName(source) {
    if (!source) return source;
    const [nomParts, prenomParts] = _parseParts(source);
    if (nomParts.length && prenomParts.length) {
        return `${prenomParts.join(' ')} ${nomParts.join(' ')}`;
    }
    if (nomParts.length) {
        return nomParts.join(' ');
    }
    return source.replace(/\.\w+$/, '').replace(/_/g, ' ');
}

/**
 * Normalise le nom pour comparaison (minuscule).
 * 'P00011_MARTIN_Jean_Claude.pdf' → 'jean claude martin'
 */
export function normalizePatientName(source) {
    if (!source) return '';
    const [nomParts, prenomParts] = _parseParts(source);
    if (nomParts.length && prenomParts.length) {
        return `${prenomParts.join(' ').toLowerCase()} ${nomParts.join(' ').toLowerCase()}`;
    }
    if (nomParts.length) {
        return nomParts.join(' ').toLowerCase();
    }
    return source.replace(/\.\w+$/, '').toLowerCase();
}

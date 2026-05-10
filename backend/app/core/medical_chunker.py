"""
medical_chunker.py — Chunker spécialisé pour documents médicaux.

RÔLE
─────
Découpe un texte médical en chunks (fragments) avec leurs métadonnées.
Utilisé comme alternative au chunker principal (document_processor.py)
quand on veut un découpage basé sur les SECTIONS médicales plutôt que
sur la taille fixe.

DIFFÉRENCE AVEC document_processor.py
───────────────────────────────────────
  document_processor.py  → découpe par taille fixe (settings.CHUNK_SIZE)
                           + sémantique (semantic_chunk_rich)
  medical_chunker.py     → découpe par SECTION médicale détectée
                           → chaque section = un ou plusieurs chunks

SECTIONS DÉTECTÉES
───────────────────
MOTIF, ANTÉCÉDENTS, HISTOIRE, MODE DE VIE, EXAMEN, CONCLUSION,
TRAITEMENT, OBSERVATION, HOSPITALISATION, COMPTE RENDU, etc.
(voir SECTION_PATTERNS pour la liste complète)

USAGE
──────
  chunker = get_medical_chunker()
  chunks = chunker.process_document(texte_pdf)
  # Retourne : [{"content": "...", "metadata": {"section": "TRAITEMENT", ...}}]
"""

import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


from app.config import settings

class MedicalChunker:
    """Chunker spécialisé pour documents médicaux"""
    
    # Patterns de détection de sections (headers)
    SECTION_PATTERNS = [
        r"^#*\s*(MOTIF|ANT[EÉ]C[EÉ]DENTS|HISTOIRE|MODE DE VIE|EXAMEN|CONCLUSION|TRAITEMENT|OBSERVATION|CLINIQUE|AMBULATOIRE|HOSPITALISATION|COMPTE RENDU|NUM[EÉ]RO|MEDECIN).*",
        r"^[A-ZÉÈÀ\s-]{4,}:?$"
    ]
    
    # Patterns de détection de dates
    DATE_PATTERNS = [
        r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        r"\d{4}[/-]\d{1,2}[/-]\d{1,2}",
        r"\d{1,2}\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre)\s+\d{2,4}"
    ]

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
        min_chunk_size: int = 150
    ):
        """
        Args:
            chunk_size: Taille cible des chunks (défaut: settings.CHUNK_SIZE)
            chunk_overlap: Overlap entre chunks (défaut: settings.CHUNK_OVERLAP)
            min_chunk_size: Taille minimale d'un chunk
        """
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP
        self.min_chunk_size = min_chunk_size
    
    def detect_section(self, text: str) -> str | None:
        """Détecte le nom de la section médicale"""
        for pattern in self.SECTION_PATTERNS:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                # Extraire le nom de la section (groupe 1 ou texte complet)
                section = match.group(1) if match.groups() else match.group(0)
                # Nettoyer
                section = section.strip().strip('#').strip().upper()
                return section
        return None
    
    def extract_dates(self, text: str) -> List[str]:
        """Extrait les dates du texte"""
        dates = []
        for pattern in self.DATE_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            dates.extend(matches)
        return dates[:3]  # Max 3 dates par chunk
    
    def split_by_sections(self, text: str) -> List[Tuple[str, str]]:
        """
        Divise le texte par sections médicales
        Returns: List[(section_name, section_content)]
        """
        sections = []
        current_section = "GÉNÉRAL"
        current_content = []
        
        lines = text.split('\n')
        
        for line in lines:
            # Vérifier si c'est un header de section
            section_name = self.detect_section(line)
            
            if section_name:
                # Sauvegarder la section précédente
                if current_content:
                    sections.append((
                        current_section,
                        '\n'.join(current_content)
                    ))
                
                # Commencer nouvelle section
                current_section = section_name
                current_content = [line]
            else:
                current_content.append(line)
        
        # Ajouter la dernière section
        if current_content:
            sections.append((
                current_section,
                '\n'.join(current_content)
            ))
        
        return sections
    
    def chunk_text(
        self,
        text: str,
        section_name: str = "GÉNÉRAL"
    ) -> List[Dict]:
        """
        Découpe un texte en chunks avec metadata
        
        Returns:
            List[Dict] avec keys: content, metadata
        """
        chunks = []
        
        # Split en paragraphes
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        current_chunk = []
        current_size = 0
        
        for para in paragraphs:
            para_size = len(para)
            
            # Si le paragraphe seul dépasse chunk_size, le couper
            if para_size > self.chunk_size:
                # Sauvegarder chunk actuel
                if current_chunk:
                    chunk_text = '\n\n'.join(current_chunk)
                    chunks.append(self._create_chunk(chunk_text, section_name))
                    current_chunk = []
                    current_size = 0
                
                # Découper le gros paragraphe
                words = para.split()
                temp_chunk = []
                temp_size = 0
                
                for word in words:
                    word_size = len(word) + 1
                    if temp_size + word_size > self.chunk_size and temp_chunk:
                        chunk_text = ' '.join(temp_chunk)
                        chunks.append(self._create_chunk(chunk_text, section_name))
                        # Overlap
                        overlap_words = temp_chunk[-10:] if len(temp_chunk) > 10 else temp_chunk
                        temp_chunk = overlap_words + [word]
                        temp_size = sum(len(w) + 1 for w in temp_chunk)
                    else:
                        temp_chunk.append(word)
                        temp_size += word_size
                
                if temp_chunk:
                    chunk_text = ' '.join(temp_chunk)
                    chunks.append(self._create_chunk(chunk_text, section_name))
            
            # Paragraphe normal
            elif current_size + para_size > self.chunk_size and current_chunk:
                # Sauvegarder chunk actuel
                chunk_text = '\n\n'.join(current_chunk)
                chunks.append(self._create_chunk(chunk_text, section_name))
                
                # Commencer nouveau chunk avec overlap
                if len(current_chunk) > 1:
                    current_chunk = [current_chunk[-1], para]
                    current_size = len(current_chunk[-2]) + para_size
                else:
                    current_chunk = [para]
                    current_size = para_size
            else:
                current_chunk.append(para)
                current_size += para_size
        
        # Dernier chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            if len(chunk_text) >= self.min_chunk_size:
                chunks.append(self._create_chunk(chunk_text, section_name))
        
        return chunks
    
    def _create_chunk(self, text: str, section_name: str) -> Dict:
        """Crée un chunk avec metadata"""
        # Extraire dates
        dates = self.extract_dates(text)
        
        metadata = {
            "section": section_name,
            "dates": dates,
            "length": len(text),
            "created_at": datetime.now().isoformat()
        }
        
        # Ajouter première date si disponible
        if dates:
            metadata["primary_date"] = dates[0]
        
        return {
            "content": text,
            "metadata": metadata
        }
    
    def process_document(
        self,
        text: str,
        document_type: str = "medical_record"
    ) -> List[Dict]:
        """
        Traite un document médical complet
        
        Returns:
            List[Dict] de chunks avec metadata
        """
        all_chunks = []
        
        # 1. Diviser par sections
        sections = self.split_by_sections(text)
        
        logger.info(f"Detected {len(sections)} sections")
        
        # 2. Chunker chaque section
        for section_name, section_content in sections:
            if not section_content.strip():
                continue
            
            section_chunks = self.chunk_text(section_content, section_name)
            
            # Ajouter type de document
            for chunk in section_chunks:
                chunk["metadata"]["document_type"] = document_type
            
            all_chunks.extend(section_chunks)
            
            logger.debug(f"Section '{section_name}': {len(section_chunks)} chunks")
        
        logger.info(f"Total chunks created: {len(all_chunks)}")
        
        return all_chunks


# Instance singleton
_medical_chunker: MedicalChunker | None = None


def get_medical_chunker() -> MedicalChunker:
    """Retourne l'instance singleton du chunker médical"""
    global _medical_chunker
    if _medical_chunker is None:
        _medical_chunker = MedicalChunker()
    return _medical_chunker

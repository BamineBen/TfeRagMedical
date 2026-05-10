import WorkshopPage from '../../components/WorkshopPage';

export default function WsRag() {
    return (
        <WorkshopPage
            title="Terminal RAG"
            realPath="/rag"
            objective="Interface de chat avec streaming SSE, sélection de patient et affichage des sources citées."
            elements={[
                'Sélecteur de patient',
                'Zone de messages (question + réponse streaming)',
                'Panneau de sources / citations',
                'Barre d\'envoi avec sélection du mode LLM',
            ]}
            starterCode={`import { useState, useRef } from 'react';

export default function RagTerminal() {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');

    const sendMessage = async () => {
        // TODO: POST /api/v1/chat/stream avec EventSource
    };

    return (
        <div className="flex flex-col h-full">
            {/* TODO: Zone messages */}
            {/* TODO: Barre d'envoi */}
        </div>
    );
}`}
            tailwindHints={['flex flex-col h-full', 'overflow-y-auto', 'bg-gray-900 text-white']}
            apiEndpoints={[
                { method: 'POST', path: '/api/v1/chat/stream', desc: 'Streaming SSE' },
                { method: 'GET', path: '/api/v1/patients', desc: 'Liste patients' },
            ]}
            reactHooks={['useState', 'useRef', 'useEffect']}
        />
    );
}

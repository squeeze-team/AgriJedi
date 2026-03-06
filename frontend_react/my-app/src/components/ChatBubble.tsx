import { useState } from 'react';
import {
  Avatar,
  MainContainer,
  ChatContainer,
  MessageList,
  Message,
} from '@chatscope/chat-ui-kit-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { API_BASE } from '../services/api';

type ChatMsg = {
  id: string;
  message: string;
  sender: string;
  direction: 'incoming' | 'outgoing';
};

type SatelliteAutofillPayload = {
  bbox: string;
  bboxList: string[];
  dateRange: string;
};

interface ChatBubbleProps {
  onAutofillSatellite?: (payload: SatelliteAutofillPayload) => void;
}

function createAssistantReply(text: string) {
  const lower = text.toLowerCase();
  if (lower.includes('yield')) {
    return 'Run Prediction first, then check Per-Crop NDVI Analysis for yield signals.';
  }
  if (lower.includes('price')) {
    return 'Use Commodity Price History for trend context and Price Forecast for short-term direction.';
  }
  if (lower.includes('satellite') || lower.includes('ndvi')) {
    return 'Pick region and date in Satellite Imagery, then click Load to refresh NDVI analysis.';
  }
  return 'I can help you navigate map, weather, price, prediction, and crop analysis modules.';
}

export function ChatBubble({ onAutofillSatellite }: ChatBubbleProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [currentStage, setCurrentStage] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      id: 'welcome',
      sender: 'Agri Assistant',
      direction: 'incoming',
      message: 'Hi, I am Agri Assistant. Ask me how to use this dashboard.',
    },
  ]);

  const appendAssistantChunk = (assistantId: string, chunk: string) => {
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === assistantId
          ? {
              ...msg,
              message: msg.message + chunk,
            }
          : msg,
      ),
    );
  };

  const sendMessage = async (content: string) => {
    const trimmed = content.trim();
    if (!trimmed) {
      return;
    }

    const userMessage: ChatMsg = {
      id: `u-${Date.now()}`,
      sender: 'You',
      direction: 'outgoing',
      message: trimmed,
    };
    const assistantId = `a-${Date.now()}`;
    const assistantPlaceholder: ChatMsg = {
      id: assistantId,
      sender: 'Agri Assistant',
      direction: 'incoming',
      message: '',
    };
    const historyForApi = messages
      .filter((msg) => msg.id !== 'welcome')
      .map((msg) => ({
        role: msg.direction === 'outgoing' ? 'user' : 'assistant',
        content: msg.message,
      }));

    setMessages((prev) => [
      ...prev,
      userMessage,
      assistantPlaceholder,
    ]);

    setIsTyping(true);
    setCurrentStage('Submitting request');
    try {
      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: trimmed,
          history: historyForApi,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let receivedDelta = false;
      let streamDone = false;

      while (!streamDone) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() ?? '';

        for (const rawEvent of events) {
          const lines = rawEvent.split('\n');
          const dataLines = lines
            .map((line) => line.trim())
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).trim());

          if (dataLines.length === 0) {
            continue;
          }

          const payload = dataLines.join('\n');
          if (!payload) {
            continue;
          }

          const evt = JSON.parse(payload) as {
            type: string;
            delta?: string;
            error?: string;
            label?: string;
            bbox?: string;
            bbox_list?: string[];
            date_range?: string;
          };
          if (evt.type === 'delta' && evt.delta) {
            receivedDelta = true;
            appendAssistantChunk(assistantId, evt.delta);
          } else if (evt.type === 'stage' && evt.label) {
            setCurrentStage(evt.label);
          } else if (evt.type === 'autofill') {
            const bboxList = Array.isArray(evt.bbox_list) ? evt.bbox_list : [];
            const bbox = evt.bbox ?? bboxList.join(',');
            const dateRange = evt.date_range ?? '';
            if (bbox && dateRange) {
              onAutofillSatellite?.({
                bbox,
                bboxList,
                dateRange,
              });
            }
          } else if (evt.type === 'done') {
            streamDone = true;
            setCurrentStage(null);
            await reader.cancel();
            break;
          } else if (evt.type === 'error') {
            streamDone = true;
            await reader.cancel();
            throw new Error(evt.error || 'Streaming failed');
          }
        }
      }

      if (!receivedDelta) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? {
                  ...msg,
                  message: createAssistantReply(trimmed),
                }
              : msg,
          ),
        );
      }
    } catch {
      setCurrentStage(null);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId
            ? {
                ...msg,
                message: createAssistantReply(trimmed),
              }
            : msg,
        ),
      );
    } finally {
      setIsTyping(false);
      setCurrentStage(null);
    }
  };

  const handleSend = () => {
    void sendMessage(draft);
    setDraft('');
  };

  const assistantAvatar =
    'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" rx="20" fill="%23111827"/><text x="20" y="25" text-anchor="middle" font-family="Arial" font-size="14" fill="white">AI</text></svg>';
  const userAvatar =
    'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" rx="20" fill="%23e5e7eb"/><text x="20" y="25" text-anchor="middle" font-family="Arial" font-size="14" fill="%23111827">You</text></svg>';

  return (
    <div className="fixed right-6 bottom-6 z-[1200]">
      {isOpen && (
        <div
          className={`openai-chat mb-3 flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl ${
            isExpanded
              ? 'h-[82vh] w-[92vw] md:h-[78vh] md:w-[70vw] lg:h-[72vh] lg:w-[50vw]'
              : 'h-[500px] w-[360px] max-w-[92vw]'
          }`}
        >
          <div className="shrink-0 border-b border-slate-200 bg-white px-4 py-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-slate-900">Agri Assistant</p>
                <p className="text-xs text-slate-500">Dashboard help</p>
              </div>
              <button
                type="button"
                onClick={() => setIsExpanded((prev) => !prev)}
                className="rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
                aria-label={isExpanded ? 'Restore chat size' : 'Expand chat size'}
              >
                {isExpanded ? 'Restore' : 'Expand'}
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1">
            <MainContainer>
              <ChatContainer>
                <MessageList>
                  {messages.map((msg) => (
                    <Message
                      key={msg.id}
                      model={{
                        message: '',
                        sender: msg.sender,
                        direction: msg.direction,
                        position: 'single',
                        type: 'custom',
                      }}
                    >
                      <Avatar name={msg.sender} src={msg.direction === 'incoming' ? assistantAvatar : userAvatar} />
                      <Message.CustomContent>
                        <div className="chat-markdown">
                          {msg.direction === 'incoming' && isTyping && msg.message.trim().length === 0 ? (
                            <span className="chat-dots chat-dots-dark chat-dots-inline" aria-label="Assistant is typing">
                              <span />
                              <span />
                              <span />
                            </span>
                          ) : (
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.message || ' '}</ReactMarkdown>
                          )}
                        </div>
                      </Message.CustomContent>
                    </Message>
                  ))}
                </MessageList>
              </ChatContainer>
            </MainContainer>
          </div>
          <div className="shrink-0 border-t border-slate-200 bg-white p-3">
            {isTyping && (
              <div className="mb-2 flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5">
                <span className="stage-spinner" />
                <span className="text-[11px] font-medium text-slate-700">{currentStage ?? 'Thinking...'}</span>
              </div>
            )}
            <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-2 py-2">
              <input
                type="text"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                disabled={isTyping}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Ask anything..."
                className="w-full bg-transparent px-2 text-sm text-slate-900 outline-none placeholder:text-slate-400"
              />
              <button
                type="button"
                onClick={handleSend}
                disabled={isTyping}
                className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-slate-800"
              >
                {isTyping ? 'Waiting' : 'Send'}
              </button>
            </div>
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex h-14 w-14 items-center justify-center rounded-full border border-slate-800 bg-slate-900 text-sm font-semibold text-white shadow-lg transition hover:bg-slate-800"
        aria-label="Toggle chat"
      >
        {isOpen ? '×' : 'AI'}
      </button>
    </div>
  );
}

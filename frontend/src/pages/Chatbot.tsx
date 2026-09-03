import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, type ChatCitation } from "../api/client";
import { Alert, Badge, Button, EmptyState, Spinner, TextField } from "../components/ui";
import Markdown from "../components/Markdown";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: ChatCitation[];
  isEmergency?: boolean;
}

export default function Chatbot() {
  const { t } = useTranslation();
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const windowRef = useRef<HTMLDivElement>(null);

  // Keep the newest message in view without forcing the whole page to jump.
  useEffect(() => {
    windowRef.current?.scrollTo({ top: windowRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const handleSend = async (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;

    setSendError(null);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    try {
      const res = await api.post("/chat/ask", { session_id: sessionId, message: text });
      setSessionId(res.data.session_id);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.data.answer,
          citations: res.data.citations,
          isEmergency: res.data.is_emergency_escalation,
        },
      ]);
    } catch {
      // Keep the user's message in the transcript and surface the failure
      // separately, rather than losing what they typed or silently
      // inserting a fake assistant reply into the conversation history.
      setSendError("Sorry, something went wrong sending that message. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="chat-page">
      <h1>{t("chatbot")}</h1>
      <Alert variant="info">{t("disclaimer")}</Alert>

      <div className="chat-window" ref={windowRef} role="log" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 && (
          <EmptyState
            icon="💬"
            title="Ask Arogya about your medicines"
            description={
              <>
                Try: "How should I store insulin?" · "What should I eat if I have diabetes?" · "What are common
                interactions with metformin?"
              </>
            }
          />
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role} ${m.isEmergency ? "emergency" : ""}`}>
            {/* Assistant replies are Markdown; the patient's own message is
                plain text and must stay literal. */}
            {m.role === "assistant" ? (
              <Markdown>{m.content}</Markdown>
            ) : (
              <div className="chat-content">{m.content}</div>
            )}
            {m.citations && m.citations.length > 0 && (
              <div className="citations">
                {m.citations.map((c, ci) => (
                  <Badge key={ci} variant="primary" title={c.label}>
                    📎 {c.label.split(" — ")[0]}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="chat-bubble assistant">
            <Spinner size="sm" label="Arogya is thinking…" />
          </div>
        )}
      </div>

      {sendError && <Alert variant="danger" onDismiss={() => setSendError(null)}>{sendError}</Alert>}

      <form className="chat-input-row" onSubmit={handleSend}>
        <TextField
          label="Message"
          hideLabel
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t("askPlaceholder")}
          autoComplete="off"
        />
        <Button type="submit" loading={busy} disabled={!input.trim()}>
          {t("send")}
        </Button>
      </form>
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type PriceOption, type SafetyFlag } from "../api/client";
import { Alert, Badge, Button, Spinner } from "./ui";
import { SafetyFlagList } from "./MedicineReviewCard";

export interface PackResult {
  is_medicine_pack: boolean;
  confidence: number;
  brand_name: string | null;
  composition: string | null;
  strength: string | null;
  manufacturer: string | null;
  form: string | null;
  expiry: string | null;
  batch: string | null;
  mrp: number | null;
  warnings: string[];
  raw_text: string;
  matched_drug_id: string | null;
  matched_generic_name: string | null;
  match_score: number | null;
  safety_flags: SafetyFlag[];
  price_options: PriceOption[];
  cheapest: PriceOption | null;
  message: string;
}

interface Props {
  /** Called when the patient accepts the reading and wants it added. */
  onUse: (result: PackResult) => void;
  onClose: () => void;
}

/**
 * Photograph a medicine pack (strip / bottle / carton) and read the printed
 * details off it.
 *
 * This exists because the prescription is often the LEAST legible thing the
 * patient has. The pack in their hand is printed, carries the composition,
 * and is far easier to photograph well. When OCR fails on a doctor's
 * handwriting, scanning the box is the realistic recovery path.
 *
 * Capture strategy, in order of preference:
 *   1. Live camera via getUserMedia — works on desktop and mobile, lets the
 *      patient line the pack up before shooting.
 *   2. A file input with capture="environment" — on a phone this opens the
 *      rear camera directly, and on desktop it is a normal file picker.
 * Permission denial or no camera falls back to (2) without an error state.
 */
export default function MedicineScanner({ onUse, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [result, setResult] = useState<PackResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setCameraOn(false);
  }, []);

  // Release the camera when this component goes away — a live track left
  // running keeps the device's camera light on, which reads as spyware.
  useEffect(() => stopCamera, [stopCamera]);

  const startCamera = async () => {
    setCameraError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
        audio: false,
      });
      streamRef.current = stream;
      setCameraOn(true);
      // The <video> only exists once cameraOn flips, so attach on next tick.
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => undefined);
        }
      }, 0);
    } catch {
      setCameraError(
        "Couldn't open the camera — you may have blocked permission, or this device has none. You can still choose a photo instead."
      );
    }
  };

  const send = async (blob: Blob, filename: string) => {
    setReading(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", new File([blob], filename, { type: blob.type || "image/jpeg" }));
      const res = await api.post<PackResult>("/prescriptions/identify-medicine", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(res.data);
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ??
          "Couldn't read that photo. Try again in better light, or type the medicine in manually."
      );
    } finally {
      setReading(false);
    }
  };

  const shoot = () => {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    setPreview(canvas.toDataURL("image/jpeg", 0.92));
    canvas.toBlob(
      (blob) => {
        if (blob) send(blob, "pack.jpg");
        stopCamera();
      },
      "image/jpeg",
      0.92
    );
  };

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setPreview(URL.createObjectURL(f));
    send(f, f.name);
  };

  const retake = () => {
    setResult(null);
    setPreview(null);
    setError(null);
  };

  return (
    <div className="scanner">
      <div className="scanner__head">
        <div>
          <h3 className="scanner__title">📷 Scan the medicine pack</h3>
          <p className="scanner__sub">
            Point at the strip, bottle or box so the printed name is clearly visible. This is often
            easier to read than the prescription itself.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => { stopCamera(); onClose(); }}>
          Close
        </Button>
      </div>

      {/* ---- Capture ---- */}
      {!result && !reading && (
        <>
          {cameraOn ? (
            <div className="scanner__stage">
              <video ref={videoRef} className="scanner__video" playsInline muted />
              <div className="scanner__guide" aria-hidden="true" />
              <div className="scanner__shootrow">
                <Button onClick={shoot}>Capture photo</Button>
                <Button variant="ghost" onClick={stopCamera}>Cancel</Button>
              </div>
            </div>
          ) : (
            <div className="scanner__choices">
              {preview && <img src={preview} alt="Captured medicine pack" className="scanner__preview" />}
              <div className="scanner__buttons">
                <Button onClick={startCamera}>Open camera</Button>
                <Button variant="ghost" onClick={() => fileRef.current?.click()}>
                  Choose a photo
                </Button>
              </div>
              {cameraError && <Alert variant="warning">{cameraError}</Alert>}
              {/* capture="environment" makes a phone open the rear camera
                  directly; desktops treat it as an ordinary file picker. */}
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                capture="environment"
                onChange={onPick}
                hidden
              />
            </div>
          )}
        </>
      )}

      {reading && (
        <div className="scanner__reading">
          {preview && <img src={preview} alt="" className="scanner__preview" />}
          <Spinner label="Reading the pack…" />
        </div>
      )}

      {error && <Alert variant="danger">{error}</Alert>}

      {/* ---- Result ---- */}
      {result && (
        <div className="scanner__result">
          {!result.is_medicine_pack ? (
            <Alert variant="warning">{result.message}</Alert>
          ) : (
            <>
              <div className="scanner__resulthead">
                <div>
                  <p className="scanner__brand">
                    {result.brand_name || result.matched_generic_name || "Name not read"}
                  </p>
                  {result.composition && <p className="scanner__comp">{result.composition}</p>}
                </div>
                <Badge
                  variant={
                    result.confidence >= 0.75 ? "success" : result.confidence >= 0.5 ? "warning" : "danger"
                  }
                >
                  {Math.round(result.confidence * 100)}% read
                </Badge>
              </div>

              <dl className="scanner__facts">
                {[
                  ["Strength", result.strength],
                  ["Form", result.form],
                  ["Made by", result.manufacturer],
                  ["Expiry", result.expiry],
                  ["Batch", result.batch],
                  ["MRP", result.mrp != null ? `₹${result.mrp}` : null],
                ].map(([label, value]) => (
                  <div key={label as string}>
                    <dt>{label}</dt>
                    <dd>{(value as string) || <span className="scanner__none">not printed / not read</span>}</dd>
                  </div>
                ))}
              </dl>

              <Alert variant={result.confidence >= 0.75 ? "info" : "warning"}>
                {result.message}
              </Alert>

              {result.warnings.length > 0 && (
                <p className="scanner__warn">⚠️ On the pack: {result.warnings.join(" · ")}</p>
              )}

              {/* A scanned pack gets the same screening a prescribed medicine
                  does — scanning must not be a way around the safety checks. */}
              {result.safety_flags.length > 0 && <SafetyFlagList flags={result.safety_flags} />}

              {result.cheapest && result.price_options.length > 1 && (
                <p className="scanner__price">
                  💰 Cheapest equivalent: <strong>{result.cheapest.product_name}</strong> ₹
                  {result.cheapest.price_inr.toFixed(0)} ({result.price_options.length} options)
                </p>
              )}

              <div className="scanner__actions">
                <Button onClick={() => { onUse(result); onClose(); }}>
                  Use these details
                </Button>
                <Button variant="ghost" onClick={retake}>Retake</Button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

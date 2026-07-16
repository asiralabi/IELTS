"use client";

import * as React from "react";
import { Play, Square, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function Equalizer({ playing }: { playing: boolean }) {
  return (
    <div className="flex h-8 items-end gap-1" aria-hidden>
      {Array.from({ length: 12 }).map((_, i) => (
        <span
          key={i}
          className={cn(
            "w-1.5 origin-bottom rounded-full bg-gradient-to-t from-primary to-accent",
            playing ? "animate-equalizer" : "scale-y-[0.35]"
          )}
          style={{ height: `${10 + ((i * 7) % 18)}px`, animationDelay: `${i * 0.09}s` }}
        />
      ))}
    </div>
  );
}

interface NeuralAudioPlayerProps {
  practiceId: number;
  /** Full-test part number; omit for a single-part practice recording. */
  part?: number;
  /** Disables playback and pauses any current playback (e.g. after submit). */
  disabled?: boolean;
  /** Fired when a fresh playback starts — use to count IELTS plays. */
  onPlayStart?: () => void;
  /** Return false to veto a fresh play (e.g. the 2-play limit is reached). */
  canPlay?: () => boolean;
}

/**
 * Plays the backend-synthesized multi-speaker MP3 for a Listening script. The
 * blob is fetched (with auth) and cached in an object URL on first play, so
 * synthesis only happens once per recording.
 */
export function NeuralAudioPlayer({
  practiceId,
  part,
  disabled = false,
  onPlayStart,
  canPlay,
}: NeuralAudioPlayerProps) {
  const audioRef = React.useRef<HTMLAudioElement | null>(null);
  const urlRef = React.useRef<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [playing, setPlaying] = React.useState(false);

  React.useEffect(() => {
    return () => {
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, []);

  React.useEffect(() => {
    if (disabled) audioRef.current?.pause();
  }, [disabled]);

  const ensureLoaded = async () => {
    if (urlRef.current) return;
    const blob = await api.listeningAudio(practiceId, part);
    const url = URL.createObjectURL(blob);
    urlRef.current = url;
    if (audioRef.current) audioRef.current.src = url;
  };

  const toggle = async () => {
    const el = audioRef.current;
    if (!el || loading) return;
    if (playing) {
      el.pause();
      return;
    }
    if (canPlay && !canPlay()) return;
    setLoading(true);
    try {
      await ensureLoaded();
      onPlayStart?.();
      await el.play();
    } catch {
      toast.error("Couldn't play the recording. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center gap-4">
      <Button
        size="icon"
        onClick={toggle}
        aria-label={playing ? "Stop audio" : "Play audio"}
        disabled={disabled || loading}
      >
        {loading ? (
          <Loader2 className="size-4 animate-spin" />
        ) : playing ? (
          <Square className="size-4" />
        ) : (
          <Play className="size-4" />
        )}
      </Button>
      <Equalizer playing={playing} />
      <audio
        ref={audioRef}
        preload="none"
        className="hidden"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
      />
    </div>
  );
}

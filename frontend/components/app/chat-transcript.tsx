"use client";

import { AnimatePresence, type HTMLMotionProps, motion } from "motion/react";
import { type ReceivedChatMessage } from "@livekit/components-react";
import { ChatEntry } from "@/components/livekit/chat-entry";

const MotionContainer = motion.create("div");
const MotionChatEntry = motion.create(ChatEntry);

const CONTAINER_MOTION_PROPS = {
  variants: {
    hidden: {
      opacity: 0,
      transition: {
        ease: "easeOut",
        duration: 0.3,
        staggerChildren: 0.1,
        staggerDirection: -1,
      },
    },
    visible: {
      opacity: 1,
      transition: {
        delay: 0.2,
        ease: "easeOut",
        duration: 0.3,
        staggerChildren: 0.1,
        staggerDirection: 1,
      },
    },
  },
  initial: "hidden",
  animate: "visible",
  exit: "hidden",
};

const MESSAGE_MOTION_PROPS = {
  variants: {
    hidden: { opacity: 0, translateY: 10 },
    visible: { opacity: 1, translateY: 0 },
  },
};

interface ChatTranscriptProps {
  hidden?: boolean;
  messages?: ReceivedChatMessage[];
}

export function ChatTranscript({
  hidden = false,
  messages = [],
  ...props
}: ChatTranscriptProps & Omit<HTMLMotionProps<"div">, "ref">) {
  return (
    <div className="relative w-full h-full flex items-center justify-center">

      {/* 🌟 HOLOGRAM BACKGROUND CARD */}
      <div className="
        absolute z-0 
        w-[360px] h-[260px] 
        rounded-2xl 
        bg-black/40 
        border border-green-400/30 
        backdrop-blur-xl 
        shadow-[0_0_40px_rgba(0,255,120,0.25)]
        overflow-hidden
      ">

        {/* GRID PATTERN */}
        <div
          className="absolute inset-0 opacity-30"
          style={{
            backgroundImage:
              "linear-gradient(to right, rgba(0,255,120,0.15) 1px, transparent 1px), linear-gradient(to bottom, rgba(0,255,120,0.15) 1px, transparent 1px)",
            backgroundSize: "20px 20px",
          }}
        />

        {/* SCANNING LINE */}
        <div className="absolute inset-0 flex items-center justify-center">
          <div
            className="
              w-full h-[3px] 
              bg-green-400/80 
              shadow-[0_0_15px_rgba(0,255,120,1)]
              animate-pulse
            "
          ></div>
        </div>

      </div>
    </div>
  );
}

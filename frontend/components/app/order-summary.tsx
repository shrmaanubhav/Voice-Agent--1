"use client";

import React from "react";
import { motion } from "motion/react";
import { useSession } from "@/components/app/session-provider";

export default function OrderSummary() {
  const { order, showOrder, setShowOrder } = useSession();

  if (!showOrder || !order) return null;

  // Size → cup height
  const sizeHeights = {
    small: "h-24",
    medium: "h-32",
    large: "h-40",
  };

  const cupHeight =
    sizeHeights[(order.size || "").toLowerCase()] || "h-32";

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/60 z-[999] flex items-center justify-center"
    >
      <motion.div
        initial={{ scale: 0.8 }}
        animate={{ scale: 1 }}
        className="bg-white dark:bg-neutral-900 rounded-2xl shadow-2xl max-w-lg w-full p-6"
      >
        <h2 className="text-2xl font-bold mb-4 text-center">
          ☕ Your Coffee Order
        </h2>

        <div className="flex gap-6 justify-center items-start">
          {/* Drink Image */}
          <div className="flex flex-col items-center">
            <div
              className={`w-20 ${cupHeight} bg-brown-700 rounded-b-xl rounded-t-sm border-4 border-brown-900 relative`}
            >
              {/* whipped cream (extras) */}
              {order.extras?.includes("whipped cream") && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 w-14 h-6 bg-white rounded-full shadow-md" />
              )}
            </div>
            <p className="mt-2 capitalize text-sm text-muted-foreground">
              {order.size} Cup
            </p>
          </div>

          {/* Order Details */}
          <div className="space-y-2 flex-1">
            <p>
              <strong>Drink:</strong> {order.drinkType}
            </p>
            <p>
              <strong>Size:</strong> {order.size}
            </p>
            <p>
              <strong>Milk:</strong> {order.milk}
            </p>
            <p>
              <strong>Extras:</strong>{" "}
              {order.extras?.length > 0
                ? order.extras.join(", ")
                : "None"}
            </p>
            <p>
              <strong>Name:</strong> {order.name}
            </p>
          </div>
        </div>

        <button
          onClick={() => setShowOrder(false)}
          className="mt-6 w-full py-2 rounded-lg bg-neutral-800 text-white hover:bg-neutral-700"
        >
          Close
        </button>
      </motion.div>
    </motion.div>
  );
}

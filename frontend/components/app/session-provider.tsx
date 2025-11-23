'use client';

import { createContext, useContext, useMemo } from 'react';
import { RoomContext } from '@livekit/components-react';
import { APP_CONFIG_DEFAULTS, type AppConfig } from '@/app-config';
import { useRoom } from '@/hooks/useRoom';

const SessionContext = createContext<{
  appConfig: AppConfig;
  isSessionActive: boolean;
  startSession: () => void;
  endSession: () => void;

  // NEW ORDER STATES
  order: any;
  showOrder: boolean;
  setShowOrder: (v: boolean) => void;
}>( {
  appConfig: APP_CONFIG_DEFAULTS,
  isSessionActive: false,
  startSession: () => {},
  endSession: () => {},

  // NEW defaults
  order: null,
  showOrder: false,
  setShowOrder: () => {},
});

interface SessionProviderProps {
  appConfig: AppConfig;
  children: React.ReactNode;
}

export const SessionProvider = ({ appConfig, children }: SessionProviderProps) => {
  const {
    room,
    isSessionActive,
    startSession,
    endSession,
    order,
    showOrder,
    setShowOrder
  } = useRoom(appConfig);

  const contextValue = useMemo(
    () => ({
      appConfig,
      isSessionActive,
      startSession,
      endSession,

      // NEW
      order,
      showOrder,
      setShowOrder
    }),
    [
      appConfig,
      isSessionActive,
      startSession,
      endSession,
      order,
      showOrder,
      setShowOrder
    ]
  );

  return (
    <RoomContext.Provider value={room}>
      <SessionContext.Provider value={contextValue}>
        {children}
      </SessionContext.Provider>
    </RoomContext.Provider>
  );
};

export function useSession() {
  return useContext(SessionContext);
}

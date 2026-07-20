import React from 'react';
import { HorizonCard } from './HorizonCard';

interface WidgetProps {
  icon: React.ReactNode;
  title: string;
  subtitle: string | number;
}

export const HorizonWidget: React.FC<WidgetProps> = ({ icon, title, subtitle }) => {
  return (
    <HorizonCard extra="!flex-row flex-grow items-center rounded-[20px] p-4 bg-nexus-sf border border-white/5 shadow-md">
      <div className="flex h-[80px] w-auto flex-row items-center">
        <div className="rounded-full bg-nexus-bg p-4 flex items-center justify-center w-12 h-12">
          <span className="flex items-center text-nexus-pur">
            {icon}
          </span>
        </div>
      </div>

      <div className="h-50 ml-4 flex w-auto flex-col justify-center">
        <p className="font-dm text-sm font-medium text-gray-500 dark:text-gray-400">{title}</p>
        <h4 className="text-2xl font-bold text-navy-900 dark:text-white">
          {subtitle}
        </h4>
      </div>
    </HorizonCard>
  );
};

import React from 'react';

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  extra?: string;
  children: React.ReactNode;
}

export const HorizonCard: React.FC<CardProps> = ({ extra = '', children, ...rest }) => {
  return (
    <div
      className={`relative flex flex-col rounded-[20px] bg-nexus-sf border border-white/5 bg-clip-border shadow-md text-white ${extra}`}
      {...rest}
    >
      {children}
    </div>
  );
};

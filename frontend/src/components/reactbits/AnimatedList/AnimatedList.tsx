// From React Bits (https://reactbits.dev/r/AnimatedList-TS-TW), MIT + Commons Clause.
// Local changes: generic items with a renderItem callback (the original renders strings only);
// keyboard navigation is scoped to the focused list instead of a window-wide listener that
// captured Tab for the whole page; fixed 500px width and hard-coded colours replaced by props.
'use client';

import React, { useRef, useState, useEffect, useCallback, type ReactNode, type MouseEventHandler, type UIEvent } from 'react';
import { motion, useInView } from 'motion/react';

interface AnimatedItemProps {
  children: ReactNode;
  delay?: number;
  index: number;
  onMouseEnter?: MouseEventHandler<HTMLDivElement>;
  onClick?: MouseEventHandler<HTMLDivElement>;
}

const AnimatedItem: React.FC<AnimatedItemProps> = ({ children, delay = 0, index, onMouseEnter, onClick }) => {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.5, once: false });
  return (
    <motion.div
      ref={ref}
      data-index={index}
      onMouseEnter={onMouseEnter}
      onClick={onClick}
      initial={{ scale: 0.7, opacity: 0 }}
      animate={inView ? { scale: 1, opacity: 1 } : { scale: 0.7, opacity: 0 }}
      transition={{ duration: 0.2, delay }}
      className="mb-3 cursor-pointer"
    >
      {children}
    </motion.div>
  );
};

interface AnimatedListProps<T> {
  items: T[];
  renderItem: (item: T, index: number, selected: boolean) => ReactNode;
  onItemSelect?: (item: T, index: number) => void;
  showGradients?: boolean;
  enableArrowNavigation?: boolean;
  className?: string;
  maxHeightClass?: string;
  gradientFromClass?: string;
  initialSelectedIndex?: number;
  ariaLabel?: string;
}

function AnimatedList<T>({
  items,
  renderItem,
  onItemSelect,
  showGradients = true,
  enableArrowNavigation = true,
  className = '',
  maxHeightClass = 'max-h-[400px]',
  gradientFromClass = 'from-surface',
  initialSelectedIndex = -1,
  ariaLabel
}: AnimatedListProps<T>) {
  const listRef = useRef<HTMLDivElement>(null);
  const [selectedIndex, setSelectedIndex] = useState<number>(initialSelectedIndex);
  const [keyboardNav, setKeyboardNav] = useState<boolean>(false);
  const [topGradientOpacity, setTopGradientOpacity] = useState<number>(0);
  const [bottomGradientOpacity, setBottomGradientOpacity] = useState<number>(1);

  const handleItemClick = useCallback(
    (item: T, index: number) => {
      setSelectedIndex(index);
      onItemSelect?.(item, index);
    },
    [onItemSelect]
  );

  const handleScroll = (e: UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.target as HTMLDivElement;
    setTopGradientOpacity(Math.min(scrollTop / 50, 1));
    const bottomDistance = scrollHeight - (scrollTop + clientHeight);
    setBottomGradientOpacity(scrollHeight <= clientHeight ? 0 : Math.min(bottomDistance / 50, 1));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!enableArrowNavigation) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setKeyboardNav(true);
      setSelectedIndex(prev => Math.min(prev + 1, items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setKeyboardNav(true);
      setSelectedIndex(prev => Math.max(prev - 1, 0));
    } else if (e.key === 'Enter' && selectedIndex >= 0 && selectedIndex < items.length) {
      e.preventDefault();
      onItemSelect?.(items[selectedIndex], selectedIndex);
    }
  };

  useEffect(() => {
    if (!keyboardNav || selectedIndex < 0 || !listRef.current) return;
    const container = listRef.current;
    const selectedItem = container.querySelector(`[data-index="${selectedIndex}"]`) as HTMLElement | null;
    if (selectedItem) {
      const extraMargin = 50;
      const itemTop = selectedItem.offsetTop;
      const itemBottom = itemTop + selectedItem.offsetHeight;
      if (itemTop < container.scrollTop + extraMargin) {
        container.scrollTo({ top: itemTop - extraMargin, behavior: 'smooth' });
      } else if (itemBottom > container.scrollTop + container.clientHeight - extraMargin) {
        container.scrollTo({ top: itemBottom - container.clientHeight + extraMargin, behavior: 'smooth' });
      }
    }
    setKeyboardNav(false);
  }, [selectedIndex, keyboardNav]);

  useEffect(() => {
    const el = listRef.current;
    if (el) setBottomGradientOpacity(el.scrollHeight <= el.clientHeight ? 0 : 1);
  }, [items.length]);

  return (
    <div className={`relative w-full ${className}`}>
      <div
        ref={listRef}
        role="listbox"
        aria-label={ariaLabel}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className={`${maxHeightClass} overflow-y-auto p-1 pr-2 outline-none focus-visible:ring-2 focus-visible:ring-lstm/60 rounded-lg`}
        onScroll={handleScroll}
        style={{ scrollbarWidth: 'thin', scrollbarColor: 'var(--axis) transparent' }}
      >
        {items.map((item, index) => (
          <AnimatedItem
            key={index}
            delay={0.05}
            index={index}
            onMouseEnter={() => setSelectedIndex(index)}
            onClick={() => handleItemClick(item, index)}
          >
            {renderItem(item, index, selectedIndex === index)}
          </AnimatedItem>
        ))}
      </div>
      {showGradients && (
        <>
          <div
            className={`absolute top-0 left-0 right-0 h-[40px] bg-gradient-to-b ${gradientFromClass} to-transparent pointer-events-none transition-opacity duration-300`}
            style={{ opacity: topGradientOpacity }}
          />
          <div
            className={`absolute bottom-0 left-0 right-0 h-[60px] bg-gradient-to-t ${gradientFromClass} to-transparent pointer-events-none transition-opacity duration-300`}
            style={{ opacity: bottomGradientOpacity }}
          />
        </>
      )}
    </div>
  );
}

export default AnimatedList;

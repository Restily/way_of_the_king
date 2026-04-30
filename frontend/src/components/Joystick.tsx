/**
 * Виртуальный джойстик через nipplejs — для touch-управления в Mini App.
 *
 * На десктопе nipplejs тоже работает (мышь = touch), keyboard support
 * добавляется отдельно в Playground через WASD listener.
 *
 * Передаёт нормализованный input vector через `onInput` callback.
 * Координаты: x ∈ [-1, 1] (right positive), y ∈ [-1, 1] (down positive).
 */

import nipplejs, { type JoystickManager } from 'nipplejs';
import { useEffect, useRef } from 'react';

export interface JoystickProps {
  onInput: (input: { x: number; y: number }) => void;
}

export function Joystick({ onInput }: JoystickProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // Latest callback в ref'е — чтобы не пересоздавать nipplejs manager при каждом render.
  const onInputRef = useRef(onInput);
  onInputRef.current = onInput;

  useEffect(() => {
    if (!containerRef.current) return;
    const manager: JoystickManager = nipplejs.create({
      zone: containerRef.current,
      mode: 'static',
      position: { left: '60px', bottom: '60px' },
      color: '#ffd34a',
      size: 110,
    });

    manager.on('move', (_evt, data) => {
      if (!data.vector) return;
      // nipplejs: y > 0 = up, мы хотим y > 0 = down → invert.
      onInputRef.current({ x: data.vector.x, y: -data.vector.y });
    });
    manager.on('end', () => {
      onInputRef.current({ x: 0, y: 0 });
    });

    return () => manager.destroy();
  }, []);

  return <div ref={containerRef} className="joystick-zone" />;
}

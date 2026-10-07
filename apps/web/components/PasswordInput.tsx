"use client";

import { useState, type InputHTMLAttributes } from "react";
import { Icon } from "./Icon";

/** A password field with an eye button to show or hide what was typed. */
export function PasswordInput({ className = "", ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <input {...props} type={visible ? "text" : "password"} className={`${className} pr-11`} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        // deliberately not containing the word "password", so the field's
        // own label stays the only element that matches it
        aria-label={visible ? "Hide characters" : "Show characters"}
        aria-pressed={visible}
        title={visible ? "Hide" : "Show"}
        className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-lg text-slate-500 hover:text-orange-600 dark:text-slate-400"
      >
        <Icon name={visible ? "eye-off" : "eye"} size={18} />
      </button>
    </div>
  );
}

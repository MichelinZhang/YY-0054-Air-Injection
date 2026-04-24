import { motion } from "framer-motion";

export default function AnimatedButton({ children, className = "", ...props }) {
  return (
    <motion.button
      whileHover={{ y: -2, scale: 1.01 }}
      whileTap={{ y: 0, scale: 0.98 }}
      transition={{ type: "spring", stiffness: 260, damping: 20 }}
      className={`btn ${className}`}
      {...props}
    >
      {children}
    </motion.button>
  );
}


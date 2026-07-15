/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        rise: '#ef4444',
        fall: '#22c55e',
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}

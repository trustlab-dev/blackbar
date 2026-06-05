# frontend/Dockerfile
FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies (Vite-based, will fetch new tree)
RUN npm install

# Copy project files
COPY . .

# Set the Vite-style env var
ENV VITE_API_URL=/api

# Expose the Vite dev server port
EXPOSE 3000

# Start the Vite dev server (host=0.0.0.0 set in vite.config.ts)
CMD ["npm", "run", "dev"]

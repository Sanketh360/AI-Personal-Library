FROM node:20-alpine

WORKDIR /app

# Copy package requirements
COPY package.json .
# Install dependencies with legacy-peer-deps override
RUN npm install --legacy-peer-deps

# Copy configurations and code files
COPY . .

# Expose Vite development server port
EXPOSE 5173

# Start development server and bind to all host interfaces
CMD ["npm", "run", "dev", "--", "--host"]

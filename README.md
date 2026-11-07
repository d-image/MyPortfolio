# My Portfolio

## Run the frontend

From the repository root, install the JavaScript dependencies and start the Vite development server:

```powershell
npm install
npm start
```

Open the local URL printed by Vite (by default, `http://localhost:5173`). You can also use `npm run dev`.

## Run the backend

In a second terminal, start the API from the `backend` directory:

```powershell
python -m pip install -r requirements.txt
python main.py
```

The frontend proxies `/api` requests to the backend at `http://127.0.0.1:8000`. See [backend/README.md](backend/README.md) for API details and tests.

## Build the frontend

```powershell
npm run build
```

import { create } from 'zustand';
import axios from 'axios';

const API_BASE_URL = 'http://localhost:8080';

export const useArgusStore = create((set, get) => ({
  documents: [],
  selectedDocumentId: null,
  graphData: { nodes: [], edges: [] },
  selectedNode: null,
  selectedEdge: null,
  isProcessing: false,
  uploadStatus: '',
  error: null,

  fetchDocuments: async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/documents`);
      set({ documents: response.data.documents });
    } catch (err) {
      console.error("Failed to load documents", err);
      // Soft fail for UI persistence
    }
  },

  selectDocument: async (docId) => {
    set({ 
      selectedDocumentId: docId, 
      selectedNode: null, 
      selectedEdge: null, 
      isProcessing: true, 
      error: null 
    });
    try {
      const response = await axios.get(`${API_BASE_URL}/documents/${docId}/graph`);
      set({ graphData: response.data, isProcessing: false });
    } catch (err) {
      console.error("Failed to load graph", err);
      set({ 
        error: err.response?.data?.detail || "Failed to fetch document graph. Ensure your backend is running.", 
        isProcessing: false 
      });
    }
  },

  uploadDocument: async (file) => {
    set({ isProcessing: true, uploadStatus: 'Uploading file to storage...', error: null });
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await axios.post(`${API_BASE_URL}/documents/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      const newDoc = response.data.document;
      
      // Update local document list state
      set((state) => {
        const docExists = state.documents.some((d) => d.id === newDoc.id);
        const updatedDocs = docExists ? state.documents : [newDoc, ...state.documents];
        return {
          documents: updatedDocs,
          uploadStatus: 'Generating graph layout...',
        };
      });

      // Automatically fetch the graph (which now performs NetworkX layout)
      await get().selectDocument(newDoc.id);
    } catch (err) {
      console.error("Upload failed", err);
      set({ 
        error: err.response?.data?.detail || "Upload and claim extraction failed. Check backend logs.", 
        isProcessing: false,
        uploadStatus: ''
      });
    }
  },

  setSelectedNode: (node) => set({ selectedNode: node, selectedEdge: null }),
  setSelectedEdge: (edge) => set({ selectedEdge: edge, selectedNode: null }),
  clearSelection: () => set({ selectedNode: null, selectedEdge: null }),

  // Coaching state
  coachingChat: [
    {
      sender: 'argus',
      text: '### Welcome to Argus Socratic Coaching!\nI am your reasoning partner, not your ghostwriter. Click on any claim or conflict in the graph, ask me questions about your logic, and let\'s strengthen your argument together.',
      status: 'allowed'
    }
  ],
  isCoachingLoading: false,

  sendCoachingMessage: async (userPrompt) => {
    const { selectedDocumentId, selectedNode, selectedEdge } = get();
    if (!selectedDocumentId) return;

    // Optimistically add user message
    const userMsg = { sender: 'user', text: userPrompt, status: 'allowed' };
    set((state) => ({ 
      coachingChat: [...state.coachingChat, userMsg],
      isCoachingLoading: true 
    }));

    try {
      const payload = {
        user_prompt: userPrompt,
        selected_claim_id: selectedNode ? selectedNode.id : null,
        selected_conflict_id: selectedEdge ? selectedEdge.id : null
      };

      const response = await axios.post(
        `${API_BASE_URL}/documents/${selectedDocumentId}/coaching`,
        payload
      );

      const botMsg = {
        sender: 'argus',
        text: response.data.coaching_response,
        status: response.data.status
      };

      set((state) => ({
        coachingChat: [...state.coachingChat, botMsg],
        isCoachingLoading: false
      }));
    } catch (err) {
      console.error("Coaching failed", err);
      const errorMsg = {
        sender: 'argus',
        text: `### ❌ Socratic Workflow Error\nFailed to receive Socratic feedback: ${err.response?.data?.detail || err.message}`,
        status: 'error'
      };
      set((state) => ({
        coachingChat: [...state.coachingChat, errorMsg],
        isCoachingLoading: false
      }));
    }
  },

  clearCoachingChat: () => set({
    coachingChat: [
      {
        sender: 'argus',
        text: '### Welcome to Argus Socratic Coaching!\nI am your reasoning partner, not your ghostwriter. Click on any claim or conflict in the graph, ask me questions about your logic, and let\'s strengthen your argument together.',
        status: 'allowed'
      }
    ]
  })
}));

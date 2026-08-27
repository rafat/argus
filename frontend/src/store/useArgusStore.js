import { create } from 'zustand';
import axios from 'axios';

const API_BASE_URL =
  import.meta.env.VITE_ARGUS_API_URL || 'http://localhost:8080';

// Keep the backend as the complete source of document history, while the main
// sidebar presents only the most recently uploaded document family.
const latestDocumentOnly = (documents = []) => {
  if (documents.length <= 1) return documents;

  const latest = documents.reduce((current, candidate) => {
    const currentTime = Date.parse(current.created_at || '') || 0;
    const candidateTime = Date.parse(candidate.created_at || '') || 0;
    return candidateTime >= currentTime ? candidate : current;
  });

  return [latest];
};

export const useArgusStore = create((set, get) => ({
  documents: [],
  selectedDocumentId: null,
  graphData: { nodes: [], edges: [] },
  selectedNode: null,
  selectedEdge: null,
  selectedIssue: null,
  isProcessing: false,
  uploadStatus: '',
  uploadProgress: 0,
  uploadProgressMessage: '',
  error: null,
  
  // Day 6 Versioning, Diffs, and Issues states
  versions: [],
  diffs: [],
  issues: [],
  pollingInterval: null,
  pollingToken: 0,

  fetchDocuments: async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/documents`);
      set({ documents: latestDocumentOnly(response.data.documents) });
    } catch (err) {
      console.error("Failed to load documents", err);
    }
  },

  selectDocument: async (docId) => {
    // In-flight polls cannot be cancelled by clearInterval once their HTTP
    // request has started.  Advance a token so stale polls cannot install a
    // new interval or fetch the completed document's graph repeatedly.
    const activeInterval = get().pollingInterval;
    if (activeInterval) {
      clearInterval(activeInterval);
    }
    const pollingToken = get().pollingToken + 1;

    set({ 
      pollingInterval: null,
      pollingToken,
      selectedDocumentId: docId, 
      selectedNode: null, 
      selectedEdge: null, 
      selectedIssue: null,
      isProcessing: true, 
      error: null,
      versions: [],
      diffs: [],
      issues: [],
      uploadProgress: 0,
      uploadProgressMessage: 'Initializing document analysis...'
    });

    const isActivePoll = () =>
      get().pollingToken === pollingToken &&
      get().selectedDocumentId === docId;

    const poll = async () => {
      try {
        const listRes = await axios.get(`${API_BASE_URL}/documents`);
        if (!isActivePoll()) return;
        const currentDoc = listRes.data.documents.find(d => d.id === docId);
        
        if (currentDoc) {
          set({ documents: latestDocumentOnly(listRes.data.documents) });
          
          if (currentDoc.status === 'failed') {
            const interval = get().pollingInterval;
            if (interval) clearInterval(interval);
            if (!isActivePoll()) return;
            set({ 
              pollingInterval: null,
              isProcessing: false,
              uploadProgress: 0,
              uploadProgressMessage: '',
              error: currentDoc.progress_message || "Asynchronous argument parsing failed."
            });
            return;
          }

          if (currentDoc.status === 'processing') {
            set({
              uploadProgress: currentDoc.progress || 0,
              uploadProgressMessage: currentDoc.progress_message || 'Processing argument network...'
            });
          }
          
          if (currentDoc.status === 'processed') {
            const interval = get().pollingInterval;
            if (interval) clearInterval(interval);
            if (!isActivePoll()) return;
            set({ pollingInterval: null, uploadProgress: 100, uploadProgressMessage: 'Processing complete!' });
            
            // Retrieve computed claim nodes & edges
            const graphRes = await axios.get(`${API_BASE_URL}/documents/${docId}/graph`);
            if (!isActivePoll()) return;
            set({ graphData: graphRes.data, isProcessing: false, uploadStatus: '', uploadProgress: 0, uploadProgressMessage: '' });
            
            // Fetch revision, issue status tracks & versions
            get().fetchVersions(docId);
            get().fetchIssues(docId);
            if (currentDoc.version_id) {
              get().fetchDiffs(docId, currentDoc.version_id);
            }
          }
        }
      } catch (err) {
        console.error("Polling error: ", err);
      }
    };

    // Run first status inquiry immediately
    await poll();

    if (!isActivePoll()) return;

    // Set polling if processing is still ongoing
    const docs = get().documents;
    const activeDoc = docs.find(d => d.id === docId);
    if (activeDoc && activeDoc.status === 'processing') {
      const intervalId = setInterval(poll, 2000);
      if (isActivePoll()) {
        set({ pollingInterval: intervalId });
      } else {
        clearInterval(intervalId);
      }
    }
  },

  uploadDocument: async (file) => {
    set({ 
      isProcessing: true, 
      uploadStatus: 'Uploading new document...', 
      uploadProgress: 2, 
      uploadProgressMessage: 'Sending document payload to backend...', 
      error: null 
    });
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await axios.post(`${API_BASE_URL}/documents/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      
      const tempDoc = {
        id: response.data.id,
        version_id: response.data.version_id,
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
        status: "processing",
        created_at: new Date().toISOString(),
        version_number: response.data.version_number,
        parent_version_id: response.data.parent_version_id,
        progress: 5.0,
        progress_message: 'Parsing text and document structure...',
      };

      set((state) => ({
        documents: [tempDoc],
        uploadStatus: 'Parsing text and extracting claims asynchronously...',
        uploadProgress: 5,
        uploadProgressMessage: 'Parsing text and document structure...',
      }));

      // Start polling for this document's completion
      await get().selectDocument(response.data.id);
    } catch (err) {
      console.error("Upload failed", err);
      set({ 
        error: err.response?.data?.detail || "Upload initiation failed. Ensure backend is active.", 
        isProcessing: false,
        uploadStatus: '',
        uploadProgress: 0,
        uploadProgressMessage: ''
      });
    }
  },

  uploadRevision: async (file) => {
    const docId = get().selectedDocumentId;
    if (!docId) return;

    const docs = get().documents;
    const activeDoc = docs.find(d => d.id === docId);
    const parentVerId = activeDoc ? activeDoc.version_id : null;

    set({ 
      isProcessing: true, 
      uploadStatus: 'Uploading revision draft...', 
      uploadProgress: 2,
      uploadProgressMessage: 'Sending revision draft payload to backend...',
      error: null 
    });
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      const url = `${API_BASE_URL}/documents/upload?document_id=${docId}&parent_version_id=${parentVerId || ''}`;
      const response = await axios.post(url, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      const tempDoc = {
        id: docId,
        version_id: response.data.version_id,
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
        status: "processing",
        created_at: new Date().toISOString(),
        version_number: response.data.version_number,
        parent_version_id: response.data.parent_version_id,
        progress: 5.0,
        progress_message: 'Parsing text and document structure...',
      };

      set((state) => ({
        documents: state.documents.map(d => d.id === docId ? tempDoc : d),
        uploadStatus: 'Diffing paragraphs & re-analyzing issues asynchronously...',
        uploadProgress: 5,
        uploadProgressMessage: 'Parsing text and document structure...',
      }));

      await get().selectDocument(docId);
    } catch (err) {
      console.error("Revision upload failed", err);
      set({ 
        error: err.response?.data?.detail || "Revision upload failed.", 
        isProcessing: false,
        uploadStatus: '',
        uploadProgress: 0,
        uploadProgressMessage: ''
      });
    }
  },

  fetchVersions: async (docId) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/documents/${docId}/versions`);
      set({ versions: res.data.versions });
    } catch (err) {
      console.error("Failed to load versions", err);
    }
  },

  fetchDiffs: async (docId, verId) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/documents/${docId}/versions/${verId}/diff`);
      set({ diffs: res.data.changes });
    } catch (err) {
      console.error("Failed to load diffs", err);
    }
  },

  fetchIssues: async (docId) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/documents/${docId}/issues`);
      set({ issues: res.data.issues });
    } catch (err) {
      console.error("Failed to load issues", err);
    }
  },

  setSelectedNode: (node) => set({ selectedNode: node, selectedEdge: null, selectedIssue: null }),
  setSelectedEdge: (edge) => set({ selectedEdge: edge, selectedNode: null, selectedIssue: null }),
  setSelectedIssue: (issue) => set({ selectedIssue: issue, selectedNode: null, selectedEdge: null }),
  clearSelection: () => set({ selectedNode: null, selectedEdge: null, selectedIssue: null }),

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
    const { selectedDocumentId, selectedNode, selectedEdge, selectedIssue } = get();
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
        selected_conflict_id: selectedEdge ? selectedEdge.id : null,
        selected_issue_id: selectedIssue ? selectedIssue.id : null,
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

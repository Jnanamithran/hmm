import { initializeApp }  from "firebase/app";
import { getDatabase }    from "firebase/database";
import { getAuth }        from "firebase/auth";

const firebaseConfig = {
  apiKey:            "AIzaSyA3qMpasv0qmPXwGPDCYWzR_avvwyr79nc",
  authDomain:        "viper-ndt.firebaseapp.com",
  databaseURL:       "https://viper-ndt-default-rtdb.firebaseio.com",
  projectId:         "viper-ndt",
  storageBucket:     "viper-ndt.firebasestorage.app",
  messagingSenderId: "1022945188924",
  appId:             "1:1022945188924:web:60a7372f51524a9e8db739",
};

const app = initializeApp(firebaseConfig);
export const db   = getDatabase(app);
export const auth = getAuth(app);

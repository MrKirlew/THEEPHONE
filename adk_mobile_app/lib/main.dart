import 'package:flutter/material.dart';
import 'unified_ai_screen.dart';
import 'splash_screen.dart';
import 'api_client.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const KirlewAIApp());
}

class KirlewAIApp extends StatelessWidget {
  const KirlewAIApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Kirlew AI Assistant',
      theme: ThemeData(
        primarySwatch: Colors.blue,
        visualDensity: VisualDensity.adaptivePlatformDensity,
      ),
      home: const AppInitializer(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class AppInitializer extends StatefulWidget {
  const AppInitializer({Key? key}) : super(key: key);

  @override
  _AppInitializerState createState() => _AppInitializerState();
}

class _AppInitializerState extends State<AppInitializer> {
  late Future<bool> _initializationFuture;

  @override
  void initState() {
    super.initState();
    _initializationFuture = _initializeApp();
  }

  Future<bool> _initializeApp() async {
    // Check backend connectivity and OLLAMA status
    try {
      // Show splash screen for at least 2 seconds
      await Future.delayed(const Duration(seconds: 2));
      
      // Check if backend is reachable
      final apiClient = ApiClient();
      final ollamaStatus = await apiClient.checkOllamaStatus();
      
      // Log status but always proceed
      if (ollamaStatus['ollama_available'] == true) {
        print('✅ OLLAMA is running and available');
      } else {
        print('⚠️ OLLAMA not available - using fallback mode');
      }
      
      return true; // Always proceed to main screen
    } catch (e) {
      print('Error during initialization: $e');
      return true; // Still proceed even if there's an error
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<bool>(
      future: _initializationFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const SplashScreen();
        } else {
          // Always go to UnifiedAIScreen
          // The backend will handle Ollama unavailability with fallback responses
          return const UnifiedAIScreen();
        }
      },
    );
  }
}
